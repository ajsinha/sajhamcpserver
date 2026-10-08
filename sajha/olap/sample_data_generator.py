# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA MCP Server - Sample Data Generator
Version: 2.9.8

Generates sample datasets for OLAP analytics demonstrations and testing.
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import duckdb

logger = logging.getLogger(__name__)


class SampleDataGenerator:
    """
    Generates sample data for OLAP analytics demonstrations.
    
    Provides pre-built datasets including:
    - Sales data with customers, products, regions
    - Customer behavior data for cohort analysis
    - Time series data for trend analysis
    """
    
    # Configuration for sample data generation
    REGIONS = ["North", "South", "East", "West", "Central"]
    PRODUCT_CATEGORIES = ["Electronics", "Furniture", "Clothing", "Food", "Office Supplies"]
    CUSTOMER_SEGMENTS = ["Enterprise", "Small Business", "Consumer", "Government"]
    PAYMENT_METHODS = ["Credit Card", "Bank Transfer", "PayPal", "Cash"]

    # Cities per region (city, state). A customer's city is picked from its region's
    # list by customer number, so adding it does not consume random numbers and the
    # generated orders stay the same.
    REGION_CITIES = {
        "North": [("Minneapolis", "MN"), ("Detroit", "MI"), ("Milwaukee", "WI"), ("Fargo", "ND")],
        "South": [("Atlanta", "GA"), ("Houston", "TX"), ("Miami", "FL"), ("Nashville", "TN")],
        "East": [("New York", "NY"), ("Boston", "MA"), ("Philadelphia", "PA"), ("Baltimore", "MD")],
        "West": [("Los Angeles", "CA"), ("Seattle", "WA"), ("Denver", "CO"), ("Phoenix", "AZ")],
        "Central": [("Chicago", "IL"), ("St. Louis", "MO"), ("Kansas City", "MO"), ("Omaha", "NE")],
    }

    # Customer tier from lifetime value: (minimum value, tier), highest first
    TIERS = [(7500, "Platinum"), (5000, "Gold"), (2500, "Silver"), (0, "Bronze")]

    # Inventory: distribution centres with their share of network demand, two
    # suppliers per category, and network-wide daily demand (units) per category.
    WAREHOUSES = [
        ("Northeast DC", "Newark, NJ", 0.30),
        ("Southeast DC", "Atlanta, GA", 0.25),
        ("Central DC", "Chicago, IL", 0.25),
        ("West DC", "Reno, NV", 0.20),
    ]
    SUPPLIERS = {
        "Electronics": ["TechSource Inc.", "Pacific Components"],
        "Furniture": ["OakLine Furnishings", "Midwest Office Works"],
        "Clothing": ["Threadworks Apparel", "Metro Garment Co."],
        "Food": ["FreshPantry Foods", "Summit Beverage Group"],
        "Office Supplies": ["PaperTrail Supply", "DeskMate Distributors"],
    }
    CATEGORY_DAILY_DEMAND = {
        "Electronics": 12, "Furniture": 4, "Clothing": 10, "Food": 30, "Office Supplies": 40,
    }
    
    PRODUCTS = {
        "Electronics": [
            ("Laptop", 899.99, 650.00),
            ("Smartphone", 699.99, 450.00),
            ("Tablet", 499.99, 320.00),
            ("Monitor", 349.99, 220.00),
            ("Headphones", 199.99, 120.00),
            ("Keyboard", 79.99, 45.00),
            ("Mouse", 49.99, 25.00),
            ("Webcam", 89.99, 55.00),
        ],
        "Furniture": [
            ("Office Desk", 499.99, 280.00),
            ("Office Chair", 299.99, 150.00),
            ("Bookshelf", 199.99, 100.00),
            ("Filing Cabinet", 149.99, 80.00),
            ("Conference Table", 899.99, 500.00),
        ],
        "Clothing": [
            ("Business Suit", 399.99, 180.00),
            ("Dress Shirt", 59.99, 25.00),
            ("Polo Shirt", 39.99, 15.00),
            ("Dress Shoes", 149.99, 70.00),
            ("Casual Jacket", 129.99, 55.00),
        ],
        "Food": [
            ("Coffee Beans 1kg", 24.99, 12.00),
            ("Tea Variety Pack", 19.99, 8.00),
            ("Snack Box", 34.99, 18.00),
            ("Beverage Pack", 29.99, 15.00),
        ],
        "Office Supplies": [
            ("Paper Box (5000)", 49.99, 28.00),
            ("Pen Set", 14.99, 5.00),
            ("Notebook Pack", 19.99, 8.00),
            ("Stapler Set", 24.99, 10.00),
            ("Whiteboard", 89.99, 45.00),
        ]
    }
    
    def __init__(self, connection=None):
        """
        Initialize the sample data generator.
        
        Args:
            connection: Optional DuckDB connection
        """
        self.conn = connection or duckdb.connect(":memory:")
    
    def generate_all_sample_data(self, 
                                  num_customers: int = 500,
                                  num_orders: int = 5000,
                                  start_date: str = "2023-01-01",
                                  end_date: str = "2024-12-31") -> Dict[str, Any]:
        """
        Generate all sample datasets for OLAP analytics.
        
        Args:
            num_customers: Number of customers to generate
            num_orders: Number of orders to generate
            start_date: Start date for order data
            end_date: End date for order data
            
        Returns:
            Dictionary with generation statistics
        """
        try:
            # Generate customers
            customers = self._generate_customers(num_customers)
            
            # Generate products
            products = self._generate_products()
            
            # Generate orders
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            orders = self._generate_orders(customers, products, num_orders, start, end)
            
            # Create tables
            self._create_tables(customers, products, orders)
            self.ensure_dataset_tables(replace=True)
            
            return {
                "success": True,
                "statistics": {
                    "customers_created": len(customers),
                    "products_created": len(products),
                    "orders_created": len(orders),
                    "date_range": f"{start_date} to {end_date}",
                    "tables_created": ["customers", "products", "orders", "sales_data",
                                       "customer_data", "inventory_data"]
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating sample data: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def _generate_customers(self, num_customers: int) -> List[Dict]:
        """Generate sample customer data."""
        customers = []
        
        for i in range(1, num_customers + 1):
            # Determine first purchase date (for cohort analysis)
            first_purchase = datetime(2023, 1, 1) + timedelta(
                days=random.randint(0, 365)
            )
            
            customer = {
                "customer_id": f"CUST{i:05d}",
                "customer_name": f"Customer {i}",
                "segment": random.choice(self.CUSTOMER_SEGMENTS),
                "region": random.choice(self.REGIONS),
                "signup_date": first_purchase,
                "lifetime_value": round(random.uniform(100, 10000), 2),
                "is_active": random.random() > 0.1  # 90% active
            }
            cities = self.REGION_CITIES[customer["region"]]
            customer["city"], customer["state"] = cities[i % len(cities)]
            customer["tier"] = next(t for floor, t in self.TIERS if customer["lifetime_value"] >= floor)
            customers.append(customer)
        
        return customers
    
    def _generate_products(self) -> List[Dict]:
        """Generate sample product data."""
        products = []
        product_id = 1
        
        for category, items in self.PRODUCTS.items():
            for name, price, cost in items:
                product = {
                    "product_id": f"PROD{product_id:04d}",
                    "product_name": name,
                    "category": category,
                    "unit_price": price,
                    "unit_cost": cost,
                    "margin_pct": round((price - cost) / price * 100, 2)
                }
                products.append(product)
                product_id += 1
        
        return products
    
    def _generate_orders(self, 
                         customers: List[Dict], 
                         products: List[Dict],
                         num_orders: int,
                         start_date: datetime,
                         end_date: datetime) -> List[Dict]:
        """Generate sample order data."""
        orders = []
        date_range = (end_date - start_date).days
        
        for i in range(1, num_orders + 1):
            customer = random.choice(customers)
            product = random.choice(products)
            
            # Generate order date (ensure it's after customer signup)
            days_offset = random.randint(0, date_range)
            order_date = start_date + timedelta(days=days_offset)
            
            # Make sure order is after customer signup
            if order_date < customer["signup_date"]:
                order_date = customer["signup_date"] + timedelta(
                    days=random.randint(0, 30)
                )
            
            # Generate quantity with some randomness
            quantity = random.choices(
                [1, 2, 3, 5, 10],
                weights=[50, 25, 15, 7, 3]
            )[0]
            
            # Apply some seasonal patterns
            month = order_date.month
            if month in [11, 12]:  # Holiday season
                quantity = int(quantity * random.uniform(1.2, 1.8))
            elif month in [6, 7, 8]:  # Summer slowdown
                quantity = max(1, int(quantity * random.uniform(0.7, 0.9)))
            
            # Calculate amounts
            amount = product["unit_price"] * quantity
            cost = product["unit_cost"] * quantity
            
            # Apply random discount
            discount_pct = random.choices(
                [0, 5, 10, 15, 20],
                weights=[60, 20, 10, 7, 3]
            )[0]
            discount = amount * (discount_pct / 100)
            
            order = {
                "order_id": f"ORD{i:06d}",
                "order_date": order_date,
                "customer_id": customer["customer_id"],
                "product_id": product["product_id"],
                "quantity": quantity,
                "unit_price": product["unit_price"],
                "amount": amount,
                "discount": discount,
                "net_amount": amount - discount,
                "cost": cost,
                "profit": amount - discount - cost,
                "region": customer["region"],
                "segment": customer["segment"],
                "category": product["category"],
                "payment_method": random.choice(self.PAYMENT_METHODS),
                "is_returned": random.random() < 0.05  # 5% return rate
            }
            orders.append(order)
        
        return orders
    
    def _create_tables(self, 
                       customers: List[Dict], 
                       products: List[Dict], 
                       orders: List[Dict]):
        """Create DuckDB tables from generated data."""
        
        # Create customers table
        self.conn.execute("""
            CREATE OR REPLACE TABLE customers (
                customer_id VARCHAR PRIMARY KEY,
                customer_name VARCHAR,
                segment VARCHAR,
                region VARCHAR,
                signup_date DATE,
                lifetime_value DECIMAL(12, 2),
                is_active BOOLEAN,
                city VARCHAR,
                state VARCHAR,
                tier VARCHAR
            )
        """)
        
        # Insert customers
        for c in customers:
            self.conn.execute("""
                INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                c["customer_id"], c["customer_name"], c["segment"],
                c["region"], c["signup_date"], c["lifetime_value"],
                c["is_active"], c["city"], c["state"], c["tier"]
            ])
        
        # Create products table
        self.conn.execute("""
            CREATE OR REPLACE TABLE products (
                product_id VARCHAR PRIMARY KEY,
                product_name VARCHAR,
                category VARCHAR,
                unit_price DECIMAL(10, 2),
                unit_cost DECIMAL(10, 2),
                margin_pct DECIMAL(5, 2)
            )
        """)
        
        # Insert products
        for p in products:
            self.conn.execute("""
                INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)
            """, [
                p["product_id"], p["product_name"], p["category"],
                p["unit_price"], p["unit_cost"], p["margin_pct"]
            ])
        
        # Create orders table
        self.conn.execute("""
            CREATE OR REPLACE TABLE orders (
                order_id VARCHAR PRIMARY KEY,
                order_date DATE,
                customer_id VARCHAR,
                product_id VARCHAR,
                quantity INTEGER,
                unit_price DECIMAL(10, 2),
                amount DECIMAL(12, 2),
                discount DECIMAL(10, 2),
                net_amount DECIMAL(12, 2),
                cost DECIMAL(12, 2),
                profit DECIMAL(12, 2),
                region VARCHAR,
                segment VARCHAR,
                category VARCHAR,
                payment_method VARCHAR,
                is_returned BOOLEAN
            )
        """)
        
        # Insert orders
        for o in orders:
            self.conn.execute("""
                INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                o["order_id"], o["order_date"], o["customer_id"],
                o["product_id"], o["quantity"], o["unit_price"],
                o["amount"], o["discount"], o["net_amount"],
                o["cost"], o["profit"], o["region"], o["segment"],
                o["category"], o["payment_method"], o["is_returned"]
            ])
        
        # Create denormalized sales_data view for OLAP
        self.conn.execute("""
            CREATE OR REPLACE VIEW sales_data AS
            SELECT 
                o.order_id,
                o.order_date,
                o.customer_id,
                c.customer_name,
                c.segment AS customer_segment,
                c.signup_date AS customer_signup_date,
                o.product_id,
                p.product_name,
                p.category AS product_category,
                o.quantity,
                o.unit_price,
                o.amount,
                o.discount,
                o.net_amount,
                o.cost,
                o.profit,
                o.region,
                o.payment_method,
                o.is_returned,
                EXTRACT(YEAR FROM o.order_date) AS order_year,
                EXTRACT(QUARTER FROM o.order_date) AS order_quarter,
                EXTRACT(MONTH FROM o.order_date) AS order_month,
                DATE_TRUNC('month', o.order_date) AS order_month_start,
                DATE_TRUNC('month', c.signup_date) AS signup_month,
                -- Column aliases the semantic layer (config/olap/dimensions.json,
                -- measures.json) refers to, so the shipped datasets resolve here.
                o.order_date AS date,
                'Q' || CAST(EXTRACT(QUARTER FROM o.order_date) AS INTEGER) AS quarter,
                o.quantity AS qty,
                o.discount AS discount_amount,
                c.segment AS segment,
                p.category AS category,
                'Rep ' || CAST(1 + (hash(o.customer_id) % 8) AS INTEGER) AS sales_rep
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            JOIN products p ON o.product_id = p.product_id
        """)
        
        logger.info("Sample data tables created successfully")

    # -- tables behind the customer_analytics and inventory_analysis datasets --

    def _relation_exists(self, name: str) -> bool:
        try:
            self.conn.execute(f"SELECT 1 FROM {name} LIMIT 0")
            return True
        except Exception:
            return False

    def _columns(self, name: str) -> set:
        try:
            return {row[0] for row in self.conn.execute(f"DESCRIBE {name}").fetchall()}
        except Exception:
            return set()

    def ensure_dataset_tables(self, replace: bool = False) -> List[str]:
        """Create ``customer_data`` (customer_analytics) and ``inventory_data``
        (inventory_analysis) from the sample star schema.

        Idempotent: without ``replace`` an existing relation is left alone, and a
        relation is skipped when the tables it is built from are absent (e.g. a
        user-supplied OLAP database with a different schema). Returns the names created.
        """
        created = []
        if (replace or not self._relation_exists("customer_data")) and \
                {"customer_id", "segment", "region", "city", "state", "tier"} <= self._columns("customers") and \
                self._relation_exists("orders") and self._relation_exists("products"):
            self._create_customer_data_view()
            created.append("customer_data")
        if (replace or not self._relation_exists("inventory_data")) and \
                {"product_id", "product_name", "category", "unit_cost", "unit_price"} <= self._columns("products"):
            self._create_inventory_table()
            created.append("inventory_data")
        if created:
            logger.info(f"OLAP dataset tables created: {', '.join(created)}")
        return created

    def _create_customer_data_view(self):
        """One row per customer and order (customers without orders appear once with
        NULL order columns), so customer counts and revenue come from one relation."""
        self.conn.execute("""
            CREATE OR REPLACE VIEW customer_data AS
            SELECT
                c.customer_id,
                c.customer_id AS id,
                c.customer_name,
                c.segment,
                c.tier,
                c.region,
                c.state,
                c.city,
                c.signup_date,
                DATE_TRUNC('month', c.signup_date) AS signup_month,
                c.lifetime_value,
                c.is_active,
                o.order_id,
                o.order_date,
                o.product_id,
                p.product_name,
                p.category,
                o.quantity,
                o.amount,
                o.discount,
                o.net_amount,
                o.profit
            FROM customers c
            LEFT JOIN orders o ON o.customer_id = c.customer_id
            LEFT JOIN products p ON p.product_id = o.product_id
        """)

    def _create_inventory_table(self):
        """One row per product and distribution centre: a stock snapshot at the end
        of the sample period. Quantities are deterministic (derived from hashes of the
        ids), so every run produces the same table."""
        warehouses = ", ".join(
            f"('{name}', '{location}', {share})" for name, location, share in self.WAREHOUSES)
        suppliers = ", ".join(
            f"('{cat}', {i}, '{sup}')" for cat, sups in self.SUPPLIERS.items() for i, sup in enumerate(sups))
        demand = ", ".join(f"('{cat}', {units})" for cat, units in self.CATEGORY_DAILY_DEMAND.items())
        self.conn.execute(f"""
            CREATE OR REPLACE TABLE inventory_data AS
            WITH wh(warehouse, warehouse_location, share) AS (VALUES {warehouses}),
                 sup(category, slot, supplier) AS (VALUES {suppliers}),
                 dem(category, units) AS (VALUES {demand}),
                 base AS (
                    SELECT p.product_id, p.product_name, p.category, p.unit_cost, p.unit_price,
                           w.warehouse, w.warehouse_location,
                           s.supplier,
                           -- network demand for the category, split across its products and
                           -- warehouses, varied +/-50% per product and warehouse
                           ROUND(d.units / COUNT(*) OVER (PARTITION BY w.warehouse, p.category) * w.share
                                 * (0.5 + (hash(p.product_id || w.warehouse) % 100) / 100.0), 2)
                               AS avg_daily_demand,
                           CAST(7 + hash(p.product_id || 'lead') % 22 AS INTEGER) AS lead_time_days,
                           (hash(w.warehouse || p.product_id || 'stock') % 1000) / 1000.0 AS stock_draw
                    FROM products p
                    CROSS JOIN wh w
                    LEFT JOIN dem d ON d.category = p.category
                    LEFT JOIN sup s ON s.category = p.category
                                   AND s.slot = CAST(hash(p.product_id) % 2 AS INTEGER)
                 )
            SELECT
                product_id, product_name, category, warehouse, warehouse_location, supplier,
                unit_cost, unit_price, avg_daily_demand, lead_time_days,
                CAST(CEIL(avg_daily_demand * lead_time_days * 1.25) AS INTEGER) AS reorder_point,
                -- stock between 0 and ~3.5x the reorder point; about 4% of rows are out of stock
                CASE WHEN stock_draw < 0.04 THEN 0
                     ELSE CAST(CEIL(avg_daily_demand * lead_time_days * 1.25 * (0.2 + 3.3 * stock_draw)) AS INTEGER)
                END AS stock_qty,
                DATE '2024-12-31' AS snapshot_date
            FROM base
        """)
        self.conn.execute("""
            CREATE OR REPLACE TABLE inventory_data AS
            SELECT *,
                   ROUND(stock_qty * unit_cost, 2) AS inventory_value,
                   ROUND(stock_qty / NULLIF(avg_daily_demand, 0), 1) AS days_of_supply,
                   CASE WHEN stock_qty = 0 THEN 'Out of Stock'
                        WHEN stock_qty <= reorder_point THEN 'Reorder'
                        WHEN stock_qty / NULLIF(avg_daily_demand, 0) > 90 THEN 'Overstock'
                        ELSE 'Healthy' END AS stock_status
            FROM inventory_data
        """)
    
    def get_table_statistics(self) -> Dict[str, Any]:
        """Get statistics about the generated tables."""
        stats = {}
        
        tables = ["customers", "products", "orders", "customer_data", "inventory_data"]
        for table in tables:
            try:
                result = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                stats[table] = {"row_count": result[0]}
            except Exception as e:
                stats[table] = {"row_count": 0, "error": "Table not found"}
        
        # Get date range for orders
        try:
            result = self.conn.execute("""
                SELECT MIN(order_date), MAX(order_date), 
                       SUM(net_amount), COUNT(DISTINCT customer_id)
                FROM orders
            """).fetchone()
            stats["orders"]["date_range"] = {
                "min": str(result[0]) if result[0] else None,
                "max": str(result[1]) if result[1] else None
            }
            stats["orders"]["total_revenue"] = float(result[2]) if result[2] else 0
            stats["orders"]["unique_customers"] = result[3] if result[3] else 0
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
            pass
        
        return stats
    
    def generate_sample_olap_config(self) -> Dict[str, Any]:
        """
        Generate sample OLAP configuration for the sample data.
        
        Returns:
            Dictionary with datasets, measures, and dimensions config
        """
        config = {
            "datasets": {
                "sales_analysis": {
                    "name": "Sales Analysis",
                    "display_name": "Sales Analysis",
                    "description": "Comprehensive sales data for multi-dimensional analysis",
                    "source_table": "sales_data",
                    "joins": [],
                    "dimensions": [
                        "order_date", "region", "product_category", 
                        "customer_segment", "payment_method", "order_year",
                        "order_quarter", "order_month", "signup_month"
                    ],
                    "measures": [
                        "revenue", "quantity", "profit", "profit_margin",
                        "order_count", "customer_count", "avg_order_value"
                    ],
                    "default_time_dimension": "order_date"
                },
                "customer_cohorts": {
                    "name": "Customer Cohorts",
                    "display_name": "Customer Cohorts",
                    "description": "Customer behavior data for cohort and retention analysis",
                    "source_table": "sales_data",
                    "joins": [],
                    "dimensions": [
                        "signup_month", "order_month_start", "customer_id",
                        "customer_segment", "region"
                    ],
                    "measures": [
                        "revenue", "order_count", "customer_count"
                    ],
                    "default_time_dimension": "order_month_start"
                }
            },
            "measures": {
                "revenue": {
                    "name": "Revenue",
                    "expression": "SUM(net_amount)",
                    "format": "currency",
                    "description": "Total revenue (net of discounts)"
                },
                "quantity": {
                    "name": "Quantity",
                    "expression": "SUM(quantity)",
                    "format": "number",
                    "description": "Total units sold"
                },
                "profit": {
                    "name": "Profit",
                    "expression": "SUM(profit)",
                    "format": "currency",
                    "description": "Total profit"
                },
                "profit_margin": {
                    "name": "Profit Margin %",
                    "expression": "ROUND(100.0 * SUM(profit) / NULLIF(SUM(net_amount), 0), 2)",
                    "format": "percentage",
                    "description": "Profit margin percentage"
                },
                "order_count": {
                    "name": "Order Count",
                    "expression": "COUNT(DISTINCT order_id)",
                    "format": "number",
                    "description": "Number of orders"
                },
                "customer_count": {
                    "name": "Customer Count",
                    "expression": "COUNT(DISTINCT customer_id)",
                    "format": "number",
                    "description": "Number of unique customers"
                },
                "avg_order_value": {
                    "name": "Avg Order Value",
                    "expression": "ROUND(SUM(net_amount) / NULLIF(COUNT(DISTINCT order_id), 0), 2)",
                    "format": "currency",
                    "description": "Average order value"
                }
            },
            "dimensions": {
                "order_date": {
                    "name": "Order Date",
                    "type": "time",
                    "column": "order_date",
                    "hierarchies": {
                        "calendar": {
                            "levels": [
                                {"name": "Year", "expression": "EXTRACT(YEAR FROM order_date)"},
                                {"name": "Quarter", "expression": "CONCAT('Q', EXTRACT(QUARTER FROM order_date))"},
                                {"name": "Month", "expression": "STRFTIME(order_date, '%Y-%m')"},
                                {"name": "Week", "expression": "STRFTIME(order_date, '%Y-W%W')"},
                                {"name": "Day", "expression": "order_date"}
                            ]
                        }
                    }
                },
                "region": {
                    "name": "Region",
                    "type": "standard",
                    "column": "region"
                },
                "product_category": {
                    "name": "Product Category",
                    "type": "standard",
                    "column": "product_category"
                },
                "customer_segment": {
                    "name": "Customer Segment",
                    "type": "standard",
                    "column": "customer_segment"
                },
                "payment_method": {
                    "name": "Payment Method",
                    "type": "standard",
                    "column": "payment_method"
                },
                "signup_month": {
                    "name": "Signup Month",
                    "type": "time",
                    "column": "signup_month"
                },
                "order_month_start": {
                    "name": "Order Month",
                    "type": "time",
                    "column": "order_month_start"
                }
            }
        }
        
        return config


def generate_sample_data_to_files(output_dir: str = "config/olap") -> Dict[str, Any]:
    """
    Generate sample data and save OLAP config to files.
    
    Args:
        output_dir: Directory to save configuration files
        
    Returns:
        Dictionary with generation results
    """
    import json
    import os
    
    generator = SampleDataGenerator()
    
    # Generate sample data
    result = generator.generate_all_sample_data()
    
    if not result["success"]:
        return result
    
    # Get sample config
    config = generator.generate_sample_olap_config()
    
    # Save config files
    os.makedirs(output_dir, exist_ok=True)
    
    with open(os.path.join(output_dir, "datasets.json"), "w") as f:
        json.dump({"datasets": config["datasets"]}, f, indent=2)
    
    with open(os.path.join(output_dir, "measures.json"), "w") as f:
        json.dump({"measures": config["measures"]}, f, indent=2)
    
    with open(os.path.join(output_dir, "dimensions.json"), "w") as f:
        json.dump({"dimensions": config["dimensions"]}, f, indent=2)
    
    result["config_files_created"] = [
        f"{output_dir}/datasets.json",
        f"{output_dir}/measures.json", 
        f"{output_dir}/dimensions.json"
    ]
    
    return result

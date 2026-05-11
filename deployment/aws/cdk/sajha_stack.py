"""
SAJHA MCP Server v4.0.0 — AWS CDK Stack
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Single stack that creates everything needed to run SAJHA on AWS:
  - VPC (2 AZs, public + private subnets, NAT gateway)
  - ECR repository (container registry)
  - ECS Fargate service behind ALB
  - RDS PostgreSQL (private subnet, auto-scaling storage)
  - S3 bucket (tool configs, data files, hot-reload source)
  - Secrets Manager (API keys, JWT secret, DB password)
  - CloudWatch log group + dashboard
  - IAM roles (least privilege)

Architecture:
    Internet → ALB (port 443) → ECS Fargate (port 3002) → RDS PostgreSQL (port 5432)
                                       ↕                           ↕
                                   S3 bucket              Secrets Manager

Usage:
    cdk deploy                                    # defaults (dev-sized)
    cdk deploy -c environment=prod                # production sizing
    cdk deploy -c cpu=2048 -c memory=4096         # custom resources
    cdk deploy -c db_instance=r6g.large           # larger RDS
"""

from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    Stack, Duration, RemovalPolicy, CfnOutput,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_ecr as ecr,
    aws_rds as rds,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    aws_logs as logs,
    aws_iam as iam,
    aws_cloudwatch as cloudwatch,
)


class SajhaStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env_name = self.node.try_get_context("environment") or "dev"
        is_prod = env_name == "prod"

        # ── VPC ──────────────────────────────────────────────
        vpc = ec2.Vpc(self, "Vpc",
            max_azs=2,
            nat_gateways=1 if is_prod else 0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(
                    name="private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                    if is_prod else ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24),
            ],
        )

        # ── ECR Repository ───────────────────────────────────
        repo = ecr.Repository(self, "Repo",
            repository_name="sajha-mcp-server",
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=10)],
        )

        # ── S3 Bucket (configs, data, plugins) ───────────────
        bucket = s3.Bucket(self, "ConfigBucket",
            bucket_name=f"sajha-{env_name}-{self.account}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            auto_delete_objects=not is_prod,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # ── Secrets Manager ──────────────────────────────────
        db_secret = secretsmanager.Secret(self, "DbSecret",
            secret_name=f"sajha/{env_name}/database",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "sajha"}',
                generate_string_key="password",
                exclude_characters="/@\"\\",
                password_length=32,
            ),
        )

        app_secret = secretsmanager.Secret(self, "AppSecret",
            secret_name=f"sajha/{env_name}/app",
            description="SAJHA application secrets (JWT, API keys)",
        )

        # ── RDS PostgreSQL ───────────────────────────────────
        db_instance_type = self.node.try_get_context("db_instance") or (
            "t4g.medium" if is_prod else "t4g.micro")

        database = rds.DatabaseInstance(self, "Database",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16_4),
            instance_type=ec2.InstanceType(db_instance_type),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                         if is_prod else ec2.SubnetType.PRIVATE_ISOLATED),
            database_name="sajha",
            credentials=rds.Credentials.from_secret(db_secret),
            allocated_storage=20,
            max_allocated_storage=100 if is_prod else 50,
            multi_az=is_prod,
            backup_retention=Duration.days(7 if is_prod else 1),
            deletion_protection=is_prod,
            removal_policy=RemovalPolicy.SNAPSHOT if is_prod else RemovalPolicy.DESTROY,
            cloudwatch_logs_exports=["postgresql"],
        )

        # ── CloudWatch Log Group ─────────────────────────────
        log_group = logs.LogGroup(self, "LogGroup",
            log_group_name=f"/sajha/{env_name}",
            retention=logs.RetentionDays.ONE_MONTH if is_prod else logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── ECS Cluster ──────────────────────────────────────
        cluster = ecs.Cluster(self, "Cluster",
            vpc=vpc,
            cluster_name=f"sajha-{env_name}",
            container_insights_v2=ecs.ContainerInsights.ENABLED if is_prod else ecs.ContainerInsights.DISABLED,
        )

        # ── Task sizing ──────────────────────────────────────
        cpu = int(self.node.try_get_context("cpu") or (1024 if is_prod else 512))
        memory = int(self.node.try_get_context("memory") or (2048 if is_prod else 1024))
        desired_count = int(self.node.try_get_context("desired_count") or (2 if is_prod else 1))

        # ── ECS Fargate Service (behind ALB) ─────────────────
        fargate = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "Service",
            cluster=cluster,
            cpu=cpu,
            memory_limit_mib=memory,
            desired_count=desired_count,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_ecr_repository(repo, tag="latest"),
                container_port=3002,
                environment={
                    "SAJHA_STORAGE_BACKEND": "s3",
                    "SAJHA_S3_BUCKET": bucket.bucket_name,
                    "SAJHA_S3_PREFIX": "config/",
                    "SAJHA_DB_TYPE": "postgresql",
                    "SAJHA_DB_NAME": "sajha",
                    "SAJHA_SERVER_HOST": "0.0.0.0",
                    "SAJHA_SERVER_PORT": "3002",
                    "AWS_DEFAULT_REGION": self.region,
                },
                secrets={
                    "SAJHA_DB_HOST": ecs.Secret.from_secrets_manager(db_secret, "host"),
                    "SAJHA_DB_PORT": ecs.Secret.from_secrets_manager(db_secret, "port"),
                    "SAJHA_DB_USER": ecs.Secret.from_secrets_manager(db_secret, "username"),
                    "SAJHA_DB_PASSWORD": ecs.Secret.from_secrets_manager(db_secret, "password"),
                    "SAJHA_JWT_SECRET": ecs.Secret.from_secrets_manager(app_secret, "jwt_secret"),
                },
                log_driver=ecs.LogDriver.aws_logs(
                    log_group=log_group, stream_prefix="sajha"),
            ),
            public_load_balancer=True,
            health_check_grace_period=Duration.seconds(60),
        )

        # ── Health check ─────────────────────────────────────
        fargate.target_group.configure_health_check(
            path="/health",
            interval=Duration.seconds(30),
            timeout=Duration.seconds(10),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3,
        )

        # ── Auto-scaling ─────────────────────────────────────
        if is_prod:
            scaling = fargate.service.auto_scale_task_count(
                min_capacity=2, max_capacity=6)
            scaling.scale_on_cpu_utilization("CpuScaling",
                target_utilization_percent=70,
                scale_in_cooldown=Duration.seconds(60),
                scale_out_cooldown=Duration.seconds(60))

        # ── IAM: Grant S3, Secrets, RDS access ───────────────
        bucket.grant_read_write(fargate.task_definition.task_role)
        db_secret.grant_read(fargate.task_definition.task_role)
        app_secret.grant_read(fargate.task_definition.task_role)
        database.connections.allow_from(
            fargate.service, ec2.Port.tcp(5432), "ECS → RDS")

        # Bedrock access (for LLM Gateway)
        fargate.task_definition.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:ListFoundationModels"],
                resources=["*"],
            ))

        # ── CloudWatch Dashboard ─────────────────────────────
        dashboard = cloudwatch.Dashboard(self, "Dashboard",
            dashboard_name=f"sajha-{env_name}")

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="ECS CPU & Memory",
                left=[fargate.service.metric_cpu_utilization(),
                      fargate.service.metric_memory_utilization()]),
            cloudwatch.GraphWidget(
                title="ALB Requests",
                left=[fargate.load_balancer.metric_request_count(),
                      fargate.load_balancer.metric_target_response_time()]),
            cloudwatch.GraphWidget(
                title="RDS Connections",
                left=[database.metric_database_connections()]),
        )

        # ── Outputs ──────────────────────────────────────────
        CfnOutput(self, "AlbUrl",
            value=f"http://{fargate.load_balancer.load_balancer_dns_name}",
            description="SAJHA MCP Server URL")
        CfnOutput(self, "EcrRepo",
            value=repo.repository_uri,
            description="Push container images here")
        CfnOutput(self, "S3Bucket",
            value=bucket.bucket_name,
            description="Upload tool configs and plugins here")
        CfnOutput(self, "WebSocketUrl",
            value=f"ws://{fargate.load_balancer.load_balancer_dns_name}/mcp/ws",
            description="WebSocket MCP endpoint")
        CfnOutput(self, "LogGroup",
            value=log_group.log_group_name,
            description="CloudWatch log group")

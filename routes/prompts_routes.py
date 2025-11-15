"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Prompts Routes for SAJHA MCP Server - FIXED VERSION
"""

from flask import render_template, request, jsonify
from routes.base_routes import BaseRoutes
import json


class PromptsRoutes(BaseRoutes):
    """Prompts-related routes"""

    def __init__(self, auth_manager, prompts_registry):
        """Initialize prompts routes"""
        super().__init__(auth_manager)
        self.prompts_registry = prompts_registry

    def _get_categories_from_prompts(self, prompts):
        """Extract unique categories from prompts list"""
        categories = set()
        for prompt in prompts:
            if isinstance(prompt, dict):
                category = prompt.get('metadata', {}).get('category', 'general')
            else:
                category = getattr(prompt, 'category', 'general')
            categories.add(category)
        return sorted(list(categories))

    def _get_tags_from_prompts(self, prompts):
        """Extract unique tags from prompts list"""
        tags = set()
        for prompt in prompts:
            if isinstance(prompt, dict):
                prompt_tags = prompt.get('metadata', {}).get('tags', [])
            else:
                prompt_tags = getattr(prompt, 'tags', [])

            if isinstance(prompt_tags, list):
                tags.update(prompt_tags)
        return sorted(list(tags))

    def _calculate_metrics(self, prompts):
        """Calculate metrics from prompts list"""
        if not prompts:
            return {
                'categories': 0,
                'tags': 0,
                'total_renders': 0
            }

        categories = set()
        tags = set()
        total_renders = 0

        for prompt in prompts:
            if isinstance(prompt, dict):
                category = prompt.get('metadata', {}).get('category', 'general')
                prompt_tags = prompt.get('metadata', {}).get('tags', [])
                usage_count = prompt.get('metadata', {}).get('usage_count', 0)
            else:
                category = getattr(prompt, 'category', 'general')
                prompt_tags = getattr(prompt, 'tags', [])
                usage_count = getattr(prompt, 'usage_count', 0)

            categories.add(category)
            if isinstance(prompt_tags, list):
                tags.update(prompt_tags)
            total_renders += usage_count

        return {
            'categories': len(categories),
            'tags': len(tags),
            'total_renders': total_renders
        }

    def register_routes(self, app):
        """Register prompts routes"""

        @app.route('/prompts')
        @app.route('/prompts/list')
        @self.login_required
        def prompts_list():
            """Prompts list page"""
            user_session = self.get_user_session()

            # Get all prompts
            prompts = self.prompts_registry.get_all_prompts()

            # Get categories and tags - calculate from prompts if methods don't exist
            if hasattr(self.prompts_registry, 'get_categories'):
                categories = self.prompts_registry.get_categories()
            else:
                categories = self._get_categories_from_prompts(prompts)

            if hasattr(self.prompts_registry, 'get_tags'):
                tags = self.prompts_registry.get_tags()
            else:
                tags = self._get_tags_from_prompts(prompts)

            return render_template('prompts_list.html',
                                 user=user_session,
                                 prompts=prompts,
                                 categories=categories,
                                 tags=tags)

        @app.route('/prompts/<prompt_name>')
        @self.login_required
        def prompt_detail(prompt_name):
            """Prompt detail and edit page"""
            user_session = self.get_user_session()

            # Get prompt
            prompt = self.prompts_registry.get_prompt(prompt_name)
            if not prompt:
                return render_template('error.html',
                                     user=user_session,
                                     error="Prompt Not Found",
                                     message=f"Prompt '{prompt_name}' not found"), 404

            # Convert to dict
            prompt_data = prompt.to_dict()

            # Get JSON representation
            prompt_json = json.dumps(prompt_data, indent=2)

            return render_template('prompt_detail.html',
                                 user=user_session,
                                 prompt=prompt_data,
                                 prompt_json=prompt_json)

        @app.route('/prompts/<prompt_name>/test')
        @self.login_required
        def prompt_test(prompt_name):
            """Prompt testing page"""
            user_session = self.get_user_session()

            # Get prompt
            prompt = self.prompts_registry.get_prompt(prompt_name)
            if not prompt:
                return render_template('error.html',
                                     user=user_session,
                                     error="Prompt Not Found",
                                     message=f"Prompt '{prompt_name}' not found"), 404

            return render_template('prompt_test.html',
                                 user=user_session,
                                 prompt=prompt.to_dict())

        @app.route('/prompts/create')
        @self.admin_required
        def prompt_create_page():
            """Prompt creation page"""
            user_session = self.get_user_session()

            return render_template('prompt_create.html',
                                 user=user_session)

        @app.route('/prompts/category/<category>')
        @self.login_required
        def prompts_by_category(category):
            """Prompts filtered by category"""
            user_session = self.get_user_session()

            # Get prompts in category
            if hasattr(self.prompts_registry, 'get_prompts_by_category'):
                prompts = self.prompts_registry.get_prompts_by_category(category)
            else:
                # Filter manually
                all_prompts = self.prompts_registry.get_all_prompts()
                prompts = [p for p in all_prompts if
                          (isinstance(p, dict) and p.get('metadata', {}).get('category') == category) or
                          (hasattr(p, 'category') and p.category == category)]

            # Get all categories and tags
            all_prompts = self.prompts_registry.get_all_prompts()
            categories = self._get_categories_from_prompts(all_prompts)
            tags = self._get_tags_from_prompts(all_prompts)

            return render_template('prompts_list.html',
                                 user=user_session,
                                 prompts=prompts,
                                 categories=categories,
                                 tags=tags,
                                 active_category=category)

        @app.route('/prompts/tag/<tag>')
        @self.login_required
        def prompts_by_tag(tag):
            """Prompts filtered by tag"""
            user_session = self.get_user_session()

            # Get prompts with tag
            if hasattr(self.prompts_registry, 'get_prompts_by_tag'):
                prompts = self.prompts_registry.get_prompts_by_tag(tag)
            else:
                # Filter manually
                all_prompts = self.prompts_registry.get_all_prompts()
                prompts = []
                for p in all_prompts:
                    if isinstance(p, dict):
                        prompt_tags = p.get('metadata', {}).get('tags', [])
                    else:
                        prompt_tags = getattr(p, 'tags', [])

                    if tag in prompt_tags:
                        prompts.append(p)

            # Get all categories and tags
            all_prompts = self.prompts_registry.get_all_prompts()
            categories = self._get_categories_from_prompts(all_prompts)
            tags = self._get_tags_from_prompts(all_prompts)

            return render_template('prompts_list.html',
                                 user=user_session,
                                 prompts=prompts,
                                 categories=categories,
                                 tags=tags,
                                 active_tag=tag)

        # API Endpoints

        @app.route('/api/prompts/list', methods=['GET'])
        @self.login_required
        def api_prompts_list():
            """Get all prompts as JSON"""
            prompts = self.prompts_registry.get_all_prompts()

            return jsonify({
                'success': True,
                'count': len(prompts),
                'prompts': prompts
            })

        @app.route('/api/prompts/<prompt_name>', methods=['GET'])
        @self.login_required
        def api_prompt_get(prompt_name):
            """Get single prompt as JSON"""
            prompt = self.prompts_registry.get_prompt(prompt_name)

            if not prompt:
                return jsonify({
                    'success': False,
                    'error': 'Prompt not found'
                }), 404

            return jsonify({
                'success': True,
                'prompt': prompt.to_dict()
            })

        @app.route('/api/prompts/<prompt_name>/render', methods=['POST'])
        @self.login_required
        def api_prompt_render(prompt_name):
            """Render a prompt with provided arguments"""
            try:
                data = request.get_json()
                arguments = data.get('arguments', {})

                rendered = self.prompts_registry.render_prompt(prompt_name, arguments)

                return jsonify({
                    'success': True,
                    'prompt_name': prompt_name,
                    'rendered': rendered
                })

            except ValueError as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 400

            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Error rendering prompt: {str(e)}'
                }), 500

        @app.route('/api/prompts/create', methods=['POST'])
        @self.admin_required
        def api_prompt_create():
            """Create a new prompt"""
            try:
                data = request.get_json()

                name = data.get('name')
                if not name:
                    return jsonify({
                        'success': False,
                        'error': 'Prompt name is required'
                    }), 400

                # Check if prompt already exists
                if self.prompts_registry.get_prompt(name):
                    return jsonify({
                        'success': False,
                        'error': 'Prompt already exists'
                    }), 400

                # Create config
                config = {
                    'description': data.get('description', ''),
                    'prompt_template': data.get('prompt_template', ''),
                    'arguments': data.get('arguments', []),
                    'metadata': data.get('metadata', {})
                }

                # Create prompt
                success = self.prompts_registry.create_prompt(name, config)

                if success:
                    return jsonify({
                        'success': True,
                        'message': f'Prompt "{name}" created successfully'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Failed to create prompt'
                    }), 500

            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Error creating prompt: {str(e)}'
                }), 500

        @app.route('/api/prompts/<prompt_name>/update', methods=['PUT', 'POST'])
        @self.admin_required
        def api_prompt_update(prompt_name):
            """Update an existing prompt"""
            try:
                data = request.get_json()

                # Create config
                config = {
                    'description': data.get('description', ''),
                    'prompt_template': data.get('prompt_template', ''),
                    'arguments': data.get('arguments', []),
                    'metadata': data.get('metadata', {})
                }

                # Update prompt
                success = self.prompts_registry.update_prompt(prompt_name, config)

                if success:
                    return jsonify({
                        'success': True,
                        'message': f'Prompt "{prompt_name}" updated successfully'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Failed to update prompt'
                    }), 500

            except ValueError as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 404

            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Error updating prompt: {str(e)}'
                }), 500

        @app.route('/api/prompts/<prompt_name>/delete', methods=['DELETE', 'POST'])
        @self.admin_required
        def api_prompt_delete(prompt_name):
            """Delete a prompt"""
            try:
                success = self.prompts_registry.delete_prompt(prompt_name)

                if success:
                    return jsonify({
                        'success': True,
                        'message': f'Prompt "{prompt_name}" deleted successfully'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Failed to delete prompt'
                    }), 500

            except ValueError as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 404

            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Error deleting prompt: {str(e)}'
                }), 500

        @app.route('/api/prompts/search', methods=['GET', 'POST'])
        @self.login_required
        def api_prompts_search():
            """Search prompts"""
            if request.method == 'GET':
                query = request.args.get('q', '')
            else:
                data = request.get_json()
                query = data.get('query', '')

            if not query:
                return jsonify({
                    'success': False,
                    'error': 'Search query is required'
                }), 400

            # Search manually if method doesn't exist
            if hasattr(self.prompts_registry, 'search_prompts'):
                results = self.prompts_registry.search_prompts(query)
            else:
                # Manual search
                all_prompts = self.prompts_registry.get_all_prompts()
                results = []
                query_lower = query.lower()

                for prompt in all_prompts:
                    if isinstance(prompt, dict):
                        name = prompt.get('name', '').lower()
                        desc = prompt.get('description', '').lower()
                        tags = ' '.join(prompt.get('metadata', {}).get('tags', [])).lower()
                    else:
                        name = getattr(prompt, 'name', '').lower()
                        desc = getattr(prompt, 'description', '').lower()
                        tags = ' '.join(getattr(prompt, 'tags', [])).lower()

                    if query_lower in name or query_lower in desc or query_lower in tags:
                        results.append(prompt)

            return jsonify({
                'success': True,
                'query': query,
                'count': len(results),
                'results': results
            })

        @app.route('/api/prompts/categories', methods=['GET'])
        @self.login_required
        def api_prompts_categories():
            """Get all categories"""
            all_prompts = self.prompts_registry.get_all_prompts()
            categories = self._get_categories_from_prompts(all_prompts)

            return jsonify({
                'success': True,
                'count': len(categories),
                'categories': categories
            })

        @app.route('/api/prompts/tags', methods=['GET'])
        @self.login_required
        def api_prompts_tags():
            """Get all tags"""
            all_prompts = self.prompts_registry.get_all_prompts()
            tags = self._get_tags_from_prompts(all_prompts)

            return jsonify({
                'success': True,
                'count': len(tags),
                'tags': tags
            })

        @app.route('/api/prompts/metrics', methods=['GET'])
        @self.admin_required
        def api_prompts_metrics():
            """Get prompt usage metrics"""
            all_prompts = self.prompts_registry.get_all_prompts()
            metrics = self._calculate_metrics(all_prompts)

            return jsonify({
                'success': True,
                'metrics': metrics
            })

        @app.route('/admin/prompts')
        @self.admin_required
        def admin_prompts():
            """Admin prompts management page"""
            user_session = self.get_user_session()

            # Get all prompts
            raw_prompts = self.prompts_registry.get_all_prompts()

            # Normalize prompts to consistent dict format
            prompts = []
            for prompt in raw_prompts:
                if isinstance(prompt, dict):
                    normalized = {
                        'name': prompt.get('name', ''),
                        'description': prompt.get('description', ''),
                        'category': prompt.get('metadata', {}).get('category', 'general'),
                        'tags': prompt.get('metadata', {}).get('tags', []),
                        'argument_count': len(prompt.get('arguments', [])),
                        'usage_count': prompt.get('metadata', {}).get('usage_count', 0),
                        'last_used': prompt.get('metadata', {}).get('last_used', None),
                    }
                else:
                    normalized = {
                        'name': getattr(prompt, 'name', ''),
                        'description': getattr(prompt, 'description', ''),
                        'category': getattr(prompt, 'category', 'general'),
                        'tags': getattr(prompt, 'tags', []),
                        'argument_count': len(getattr(prompt, 'arguments', [])),
                        'usage_count': getattr(prompt, 'usage_count', 0),
                        'last_used': getattr(prompt, 'last_used', None),
                    }
                prompts.append(normalized)

            # Calculate metrics
            metrics = self._calculate_metrics(raw_prompts)

            # Get top 5 most used prompts
            sorted_prompts = sorted(prompts, key=lambda p: p['usage_count'], reverse=True)
            top_prompts = sorted_prompts[:5]

            return render_template('admin_prompts.html',
                                   user=user_session,
                                   prompts=prompts,
                                   top_prompts=top_prompts,
                                   metrics=metrics)

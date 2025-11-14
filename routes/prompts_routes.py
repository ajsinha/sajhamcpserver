"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Prompts Routes for SAJHA MCP Server
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
            
            # Get categories and tags
            categories = self.prompts_registry.get_categories()
            tags = self.prompts_registry.get_tags()

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
            prompts = self.prompts_registry.get_prompts_by_category(category)
            
            # Get all categories and tags
            categories = self.prompts_registry.get_categories()
            tags = self.prompts_registry.get_tags()

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
            prompts = self.prompts_registry.get_prompts_by_tag(tag)
            
            # Get all categories and tags
            categories = self.prompts_registry.get_categories()
            tags = self.prompts_registry.get_tags()

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
            
            results = self.prompts_registry.search_prompts(query)
            
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
            categories = self.prompts_registry.get_categories()
            
            return jsonify({
                'success': True,
                'count': len(categories),
                'categories': categories
            })

        @app.route('/api/prompts/tags', methods=['GET'])
        @self.login_required
        def api_prompts_tags():
            """Get all tags"""
            tags = self.prompts_registry.get_tags()
            
            return jsonify({
                'success': True,
                'count': len(tags),
                'tags': tags
            })

        @app.route('/api/prompts/metrics', methods=['GET'])
        @self.admin_required
        def api_prompts_metrics():
            """Get prompt usage metrics"""
            metrics = self.prompts_registry.get_prompt_metrics()
            
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
            prompts = self.prompts_registry.get_all_prompts()
            
            # Get metrics
            metrics = self.prompts_registry.get_prompt_metrics()

            return render_template('admin_prompts.html',
                                 user=user_session,
                                 prompts=prompts,
                                 metrics=metrics)

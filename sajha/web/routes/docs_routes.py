"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Documentation Routes for SAJHA MCP Server
"""

import os
import base64
from pathlib import Path
from flask import render_template, abort, send_file, jsonify
from sajha.web.routes.base_routes import BaseRoutes


class DocsRoutes(BaseRoutes):
    """Documentation routes - accessible without authentication"""

    def __init__(self, auth_manager):
        """Initialize docs routes"""
        super().__init__(auth_manager)
        # Get the docs directory path
        self.docs_dir = Path(__file__).parent.parent / 'docs'

    def register_routes(self, app):
        """Register documentation routes"""

        @app.route('/docs')
        def docs_list():
            """Documentation list page - accessible without login"""
            # Check if user is logged in for navbar display
            user = self._get_current_user()
            
            # Scan docs directory for markdown files
            docs = self._scan_docs_directory()
            
            return render_template('help/docs_list.html', user=user, docs=docs)

        @app.route('/docs/view/<path:doc_path>')
        def docs_view(doc_path):
            """View a specific markdown document - accessible without login"""
            user = self._get_current_user()
            
            # Security check - prevent directory traversal
            safe_path = self._sanitize_path(doc_path)
            if safe_path is None:
                abort(404)
            
            full_path = self.docs_dir / safe_path
            
            if not full_path.exists() or not full_path.is_file():
                abort(404)
            
            if not str(full_path).endswith('.md'):
                abort(404)
            
            # Read the markdown content
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                abort(500)
            
            # Base64 encode the content to avoid HTML entity issues in template
            content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
            
            # Get document title from filename
            doc_title = full_path.stem.replace('_', ' ').replace('-', ' ')
            
            # Get breadcrumb path
            relative_path = safe_path.replace('\\', '/').split('/')
            
            return render_template('help/docs_view.html', 
                                 user=user, 
                                 content_b64=content_b64,
                                 doc_title=doc_title,
                                 doc_path=doc_path,
                                 breadcrumb=relative_path)

        @app.route('/docs/raw/<path:doc_path>')
        def docs_raw(doc_path):
            """Get raw markdown content as JSON - for AJAX loading"""
            # Security check - prevent directory traversal
            safe_path = self._sanitize_path(doc_path)
            if safe_path is None:
                return jsonify({'error': 'Invalid path'}), 404
            
            full_path = self.docs_dir / safe_path
            
            if not full_path.exists() or not full_path.is_file():
                return jsonify({'error': 'File not found'}), 404
            
            if not str(full_path).endswith('.md'):
                return jsonify({'error': 'Invalid file type'}), 404
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return jsonify({
                    'success': True,
                    'content': content,
                    'title': full_path.stem.replace('_', ' ').replace('-', ' ')
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500

    def _get_current_user(self):
        """Get current user if logged in"""
        user = None
        try:
            from flask import session
            if 'token' in session:
                user = self.auth_manager.validate_session(session['token'])
        except:
            pass
        return user

    def _sanitize_path(self, path):
        """Sanitize path to prevent directory traversal attacks"""
        if not path:
            return None
        
        # Normalize the path
        path = path.replace('\\', '/')
        
        # Check for directory traversal attempts
        if '..' in path or path.startswith('/'):
            return None
        
        # Resolve the full path and check it's within docs directory
        try:
            full_path = (self.docs_dir / path).resolve()
            docs_resolved = self.docs_dir.resolve()
            
            if not str(full_path).startswith(str(docs_resolved)):
                return None
            
            return path
        except:
            return None

    def _scan_docs_directory(self):
        """Scan the docs directory and return structured list of documents"""
        docs = {}
        
        if not self.docs_dir.exists():
            return docs
        
        for root, dirs, files in os.walk(self.docs_dir):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            rel_root = Path(root).relative_to(self.docs_dir)
            folder_name = str(rel_root) if str(rel_root) != '.' else 'Root'
            
            md_files = [f for f in files if f.endswith('.md')]
            
            if md_files:
                if folder_name not in docs:
                    docs[folder_name] = []
                
                for f in sorted(md_files):
                    rel_path = str(rel_root / f) if str(rel_root) != '.' else f
                    # Clean up the display name
                    display_name = f[:-3].replace('_', ' ').replace('-', ' ')
                    
                    # Get file size
                    file_path = Path(root) / f
                    try:
                        size = file_path.stat().st_size
                        if size < 1024:
                            size_str = f"{size} B"
                        elif size < 1024 * 1024:
                            size_str = f"{size / 1024:.1f} KB"
                        else:
                            size_str = f"{size / (1024 * 1024):.1f} MB"
                    except:
                        size_str = "Unknown"
                    
                    docs[folder_name].append({
                        'name': display_name,
                        'filename': f,
                        'path': rel_path.replace('\\', '/'),
                        'size': size_str
                    })
        
        return docs

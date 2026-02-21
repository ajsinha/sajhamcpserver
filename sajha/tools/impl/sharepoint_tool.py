"""
SAJHA MCP Server - SharePoint Tools
Version: 2.9.8

Comprehensive SharePoint integration tools for document management,
list operations, site management, search, and workflow integration.
"""

import os
import json
import logging
import base64
from typing import Dict, Any, List, Optional
from datetime import datetime

from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)


class SharePointAuthenticator:
    """Handle SharePoint authentication methods."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.access_token = None
        self.token_expiry = None
        
    def get_access_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.access_token
        
        auth_type = self.config.get('auth_type', 'client_credentials')
        
        if auth_type == 'client_credentials':
            return self._get_client_credentials_token()
        elif auth_type == 'certificate':
            return self._get_certificate_token()
        elif auth_type == 'user_credentials':
            return self._get_user_credentials_token()
        else:
            raise ValueError(f"Unknown auth type: {auth_type}")
    
    def _get_client_credentials_token(self) -> str:
        """Get token using client credentials flow."""
        import requests
        
        tenant_id = self.config.get('tenant_id')
        client_id = self.config.get('client_id')
        client_secret = self.config.get('client_secret')
        
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        
        data = {
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default'
        }
        
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        
        token_data = response.json()
        self.access_token = token_data['access_token']
        self.token_expiry = datetime.now().replace(
            second=datetime.now().second + token_data.get('expires_in', 3600)
        )
        
        return self.access_token
    
    def _get_certificate_token(self) -> str:
        """Get token using certificate authentication."""
        # Implementation for certificate-based auth
        raise NotImplementedError("Certificate auth not yet implemented")
    
    def _get_user_credentials_token(self) -> str:
        """Get token using user credentials (ROPC flow)."""
        # Implementation for user credentials
        raise NotImplementedError("User credentials auth not yet implemented")


class SharePointBaseTool(BaseMCPTool):
    """Base class for SharePoint tools with common functionality."""
    
    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.config = config or {}
        self.site_url = self.config.get('site_url', '')
        self.authenticator = None
        self._init_auth()
    
    def _init_auth(self):
        """Initialize authentication."""
        auth_config = self.config.get('authentication', {})
        if auth_config:
            self.authenticator = SharePointAuthenticator(auth_config)
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = {
            'Accept': 'application/json;odata=verbose',
            'Content-Type': 'application/json;odata=verbose'
        }
        
        if self.authenticator:
            token = self.authenticator.get_access_token()
            headers['Authorization'] = f'Bearer {token}'
        
        return headers
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make authenticated request to SharePoint API."""
        import requests
        
        url = f"{self.site_url}/_api/{endpoint}"
        headers = self._get_headers()
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                response = requests.post(url, headers=headers, json=data)
            elif method == 'PATCH':
                response = requests.patch(url, headers=headers, json=data)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response.json() if response.content else {}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"SharePoint API error: {e}")
            raise


class SharePointDocumentTool(SharePointBaseTool):
    """
    SharePoint Document Management Tool.
    
    Operations: upload, download, search, get_metadata, list_files,
    check_out, check_in, delete, move, copy, get_versions
    """
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute document operation."""
        import time
        start_time = time.time()
        
        try:
            operation = arguments.get('operation', 'list_files')
            
            if operation == 'list_files':
                result = self._list_files(arguments)
            elif operation == 'get_file':
                result = self._get_file(arguments)
            elif operation == 'download':
                result = self._download_file(arguments)
            elif operation == 'upload':
                result = self._upload_file(arguments)
            elif operation == 'search':
                result = self._search_documents(arguments)
            elif operation == 'get_metadata':
                result = self._get_metadata(arguments)
            elif operation == 'update_metadata':
                result = self._update_metadata(arguments)
            elif operation == 'check_out':
                result = self._check_out(arguments)
            elif operation == 'check_in':
                result = self._check_in(arguments)
            elif operation == 'get_versions':
                result = self._get_versions(arguments)
            elif operation == 'delete':
                result = self._delete_file(arguments)
            elif operation == 'move':
                result = self._move_file(arguments)
            elif operation == 'copy':
                result = self._copy_file(arguments)
            else:
                return {
                    'success': False,
                    'error': f"Unknown operation: {operation}"
                }
            
            execution_time = round((time.time() - start_time) * 1000, 2)
            result['execution_time_ms'] = execution_time
            result['success'] = True
            return result
            
        except Exception as e:
            logger.error(f"SharePointDocumentTool error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _list_files(self, args: Dict) -> Dict:
        """List files in a folder."""
        folder_path = args.get('folder_path', '/Shared Documents')
        recursive = args.get('recursive', False)
        
        endpoint = f"web/GetFolderByServerRelativeUrl('{folder_path}')/Files"
        if recursive:
            endpoint = f"web/GetFolderByServerRelativeUrl('{folder_path}')?$expand=Folders,Files"
        
        response = self._make_request('GET', endpoint)
        
        files = []
        if 'd' in response and 'results' in response['d']:
            for file_data in response['d']['results']:
                files.append({
                    'name': file_data.get('Name'),
                    'url': file_data.get('ServerRelativeUrl'),
                    'size': file_data.get('Length'),
                    'created': file_data.get('TimeCreated'),
                    'modified': file_data.get('TimeLastModified'),
                    'author': file_data.get('Author', {}).get('Title') if file_data.get('Author') else None
                })
        
        return {
            'folder_path': folder_path,
            'file_count': len(files),
            'files': files
        }
    
    def _get_file(self, args: Dict) -> Dict:
        """Get file properties."""
        file_url = args.get('file_url')
        
        endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')"
        response = self._make_request('GET', endpoint)
        
        file_data = response.get('d', {})
        return {
            'name': file_data.get('Name'),
            'url': file_data.get('ServerRelativeUrl'),
            'size': file_data.get('Length'),
            'created': file_data.get('TimeCreated'),
            'modified': file_data.get('TimeLastModified'),
            'etag': file_data.get('ETag'),
            'unique_id': file_data.get('UniqueId'),
            'content_tag': file_data.get('ContentTag')
        }
    
    def _download_file(self, args: Dict) -> Dict:
        """Download file content."""
        import requests
        
        file_url = args.get('file_url')
        return_content = args.get('return_content', False)
        
        endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')/$value"
        url = f"{self.site_url}/_api/{endpoint}"
        headers = self._get_headers()
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        if return_content:
            content = base64.b64encode(response.content).decode('utf-8')
            return {
                'file_url': file_url,
                'content_type': response.headers.get('Content-Type'),
                'size': len(response.content),
                'content_base64': content
            }
        else:
            return {
                'file_url': file_url,
                'content_type': response.headers.get('Content-Type'),
                'size': len(response.content),
                'download_ready': True
            }
    
    def _upload_file(self, args: Dict) -> Dict:
        """Upload file to SharePoint."""
        import requests
        
        folder_path = args.get('folder_path')
        file_name = args.get('file_name')
        content_base64 = args.get('content_base64')
        overwrite = args.get('overwrite', True)
        
        content = base64.b64decode(content_base64)
        
        endpoint = f"web/GetFolderByServerRelativeUrl('{folder_path}')/Files/add(url='{file_name}',overwrite={str(overwrite).lower()})"
        url = f"{self.site_url}/_api/{endpoint}"
        
        headers = self._get_headers()
        headers['Content-Type'] = 'application/octet-stream'
        
        response = requests.post(url, headers=headers, data=content)
        response.raise_for_status()
        
        result = response.json()
        return {
            'uploaded': True,
            'file_url': result.get('d', {}).get('ServerRelativeUrl'),
            'file_name': file_name
        }
    
    def _search_documents(self, args: Dict) -> Dict:
        """Search documents in SharePoint."""
        query = args.get('query', '*')
        file_types = args.get('file_types', [])
        folder_path = args.get('folder_path')
        max_results = args.get('max_results', 50)
        
        # Build search query
        search_query = query
        if file_types:
            type_filter = ' OR '.join([f'FileExtension:{ext}' for ext in file_types])
            search_query = f"({query}) AND ({type_filter})"
        if folder_path:
            search_query = f"({search_query}) AND Path:{self.site_url}{folder_path}*"
        
        endpoint = f"search/query?querytext='{search_query}'&rowlimit={max_results}"
        response = self._make_request('GET', endpoint)
        
        results = []
        rows = response.get('d', {}).get('query', {}).get('PrimaryQueryResult', {}).get('RelevantResults', {}).get('Table', {}).get('Rows', {}).get('results', [])
        
        for row in rows:
            cells = {cell['Key']: cell['Value'] for cell in row.get('Cells', {}).get('results', [])}
            results.append({
                'title': cells.get('Title'),
                'path': cells.get('Path'),
                'file_type': cells.get('FileExtension'),
                'author': cells.get('Author'),
                'modified': cells.get('LastModifiedTime'),
                'size': cells.get('Size'),
                'summary': cells.get('HitHighlightedSummary')
            })
        
        return {
            'query': query,
            'result_count': len(results),
            'results': results
        }
    
    def _get_metadata(self, args: Dict) -> Dict:
        """Get file metadata/properties."""
        file_url = args.get('file_url')
        
        endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')/ListItemAllFields"
        response = self._make_request('GET', endpoint)
        
        return {
            'file_url': file_url,
            'metadata': response.get('d', {})
        }
    
    def _update_metadata(self, args: Dict) -> Dict:
        """Update file metadata."""
        file_url = args.get('file_url')
        metadata = args.get('metadata', {})
        
        # Get list item
        endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')/ListItemAllFields"
        item_response = self._make_request('GET', endpoint)
        
        item_data = item_response.get('d', {})
        item_type = item_data.get('__metadata', {}).get('type')
        
        # Update metadata
        update_data = {
            '__metadata': {'type': item_type}
        }
        update_data.update(metadata)
        
        self._make_request('PATCH', endpoint, update_data)
        
        return {
            'file_url': file_url,
            'updated': True,
            'metadata': metadata
        }
    
    def _check_out(self, args: Dict) -> Dict:
        """Check out a file."""
        file_url = args.get('file_url')
        
        endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')/CheckOut()"
        self._make_request('POST', endpoint)
        
        return {
            'file_url': file_url,
            'checked_out': True
        }
    
    def _check_in(self, args: Dict) -> Dict:
        """Check in a file."""
        file_url = args.get('file_url')
        comment = args.get('comment', '')
        check_in_type = args.get('check_in_type', 1)  # 0=Minor, 1=Major, 2=Overwrite
        
        endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')/CheckIn(comment='{comment}',checkintype={check_in_type})"
        self._make_request('POST', endpoint)
        
        return {
            'file_url': file_url,
            'checked_in': True,
            'comment': comment
        }
    
    def _get_versions(self, args: Dict) -> Dict:
        """Get file version history."""
        file_url = args.get('file_url')
        
        endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')/Versions"
        response = self._make_request('GET', endpoint)
        
        versions = []
        for v in response.get('d', {}).get('results', []):
            versions.append({
                'version_id': v.get('ID'),
                'version_label': v.get('VersionLabel'),
                'created': v.get('Created'),
                'created_by': v.get('CreatedBy', {}).get('Title') if v.get('CreatedBy') else None,
                'size': v.get('Size'),
                'is_current': v.get('IsCurrentVersion')
            })
        
        return {
            'file_url': file_url,
            'version_count': len(versions),
            'versions': versions
        }
    
    def _delete_file(self, args: Dict) -> Dict:
        """Delete a file."""
        file_url = args.get('file_url')
        recycle = args.get('recycle', True)
        
        if recycle:
            endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')/recycle()"
        else:
            endpoint = f"web/GetFileByServerRelativeUrl('{file_url}')"
        
        self._make_request('POST' if recycle else 'DELETE', endpoint)
        
        return {
            'file_url': file_url,
            'deleted': True,
            'recycled': recycle
        }
    
    def _move_file(self, args: Dict) -> Dict:
        """Move file to new location."""
        source_url = args.get('source_url')
        dest_url = args.get('destination_url')
        overwrite = args.get('overwrite', False)
        
        flags = 1 if overwrite else 0
        endpoint = f"web/GetFileByServerRelativeUrl('{source_url}')/moveto(newurl='{dest_url}',flags={flags})"
        self._make_request('POST', endpoint)
        
        return {
            'source_url': source_url,
            'destination_url': dest_url,
            'moved': True
        }
    
    def _copy_file(self, args: Dict) -> Dict:
        """Copy file to new location."""
        source_url = args.get('source_url')
        dest_url = args.get('destination_url')
        overwrite = args.get('overwrite', False)
        
        endpoint = f"web/GetFileByServerRelativeUrl('{source_url}')/copyto(strnewurl='{dest_url}',boverwrite={str(overwrite).lower()})"
        self._make_request('POST', endpoint)
        
        return {
            'source_url': source_url,
            'destination_url': dest_url,
            'copied': True
        }


class SharePointListTool(SharePointBaseTool):
    """
    SharePoint List Operations Tool.
    
    Operations: get_lists, get_list_items, create_item, update_item,
    delete_item, get_list_schema, query_items
    """
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute list operation."""
        import time
        start_time = time.time()
        
        try:
            operation = arguments.get('operation', 'get_lists')
            
            if operation == 'get_lists':
                result = self._get_lists(arguments)
            elif operation == 'get_list_items':
                result = self._get_list_items(arguments)
            elif operation == 'get_item':
                result = self._get_item(arguments)
            elif operation == 'create_item':
                result = self._create_item(arguments)
            elif operation == 'update_item':
                result = self._update_item(arguments)
            elif operation == 'delete_item':
                result = self._delete_item(arguments)
            elif operation == 'get_list_schema':
                result = self._get_list_schema(arguments)
            elif operation == 'query_items':
                result = self._query_items(arguments)
            else:
                return {
                    'success': False,
                    'error': f"Unknown operation: {operation}"
                }
            
            execution_time = round((time.time() - start_time) * 1000, 2)
            result['execution_time_ms'] = execution_time
            result['success'] = True
            return result
            
        except Exception as e:
            logger.error(f"SharePointListTool error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_lists(self, args: Dict) -> Dict:
        """Get all lists in the site."""
        endpoint = "web/lists?$filter=Hidden eq false"
        response = self._make_request('GET', endpoint)
        
        lists = []
        for lst in response.get('d', {}).get('results', []):
            lists.append({
                'id': lst.get('Id'),
                'title': lst.get('Title'),
                'description': lst.get('Description'),
                'item_count': lst.get('ItemCount'),
                'created': lst.get('Created'),
                'base_template': lst.get('BaseTemplate')
            })
        
        return {
            'list_count': len(lists),
            'lists': lists
        }
    
    def _get_list_items(self, args: Dict) -> Dict:
        """Get items from a list."""
        list_name = args.get('list_name')
        select_fields = args.get('select_fields', [])
        top = args.get('top', 100)
        skip = args.get('skip', 0)
        order_by = args.get('order_by')
        
        endpoint = f"web/lists/getbytitle('{list_name}')/items"
        params = [f"$top={top}", f"$skip={skip}"]
        
        if select_fields:
            params.append(f"$select={','.join(select_fields)}")
        if order_by:
            params.append(f"$orderby={order_by}")
        
        if params:
            endpoint += "?" + "&".join(params)
        
        response = self._make_request('GET', endpoint)
        
        items = response.get('d', {}).get('results', [])
        
        return {
            'list_name': list_name,
            'item_count': len(items),
            'items': items
        }
    
    def _get_item(self, args: Dict) -> Dict:
        """Get single list item."""
        list_name = args.get('list_name')
        item_id = args.get('item_id')
        
        endpoint = f"web/lists/getbytitle('{list_name}')/items({item_id})"
        response = self._make_request('GET', endpoint)
        
        return {
            'list_name': list_name,
            'item_id': item_id,
            'item': response.get('d', {})
        }
    
    def _create_item(self, args: Dict) -> Dict:
        """Create new list item."""
        list_name = args.get('list_name')
        item_data = args.get('item_data', {})
        
        # Get list item entity type
        list_endpoint = f"web/lists/getbytitle('{list_name}')"
        list_response = self._make_request('GET', list_endpoint)
        entity_type = list_response.get('d', {}).get('ListItemEntityTypeFullName')
        
        # Create item
        create_data = {
            '__metadata': {'type': entity_type}
        }
        create_data.update(item_data)
        
        endpoint = f"web/lists/getbytitle('{list_name}')/items"
        response = self._make_request('POST', endpoint, create_data)
        
        return {
            'list_name': list_name,
            'created': True,
            'item_id': response.get('d', {}).get('Id'),
            'item': response.get('d', {})
        }
    
    def _update_item(self, args: Dict) -> Dict:
        """Update list item."""
        list_name = args.get('list_name')
        item_id = args.get('item_id')
        item_data = args.get('item_data', {})
        
        # Get item for entity type
        item_endpoint = f"web/lists/getbytitle('{list_name}')/items({item_id})"
        item_response = self._make_request('GET', item_endpoint)
        entity_type = item_response.get('d', {}).get('__metadata', {}).get('type')
        
        # Update item
        update_data = {
            '__metadata': {'type': entity_type}
        }
        update_data.update(item_data)
        
        self._make_request('PATCH', item_endpoint, update_data)
        
        return {
            'list_name': list_name,
            'item_id': item_id,
            'updated': True
        }
    
    def _delete_item(self, args: Dict) -> Dict:
        """Delete list item."""
        list_name = args.get('list_name')
        item_id = args.get('item_id')
        recycle = args.get('recycle', True)
        
        if recycle:
            endpoint = f"web/lists/getbytitle('{list_name}')/items({item_id})/recycle()"
            self._make_request('POST', endpoint)
        else:
            endpoint = f"web/lists/getbytitle('{list_name}')/items({item_id})"
            self._make_request('DELETE', endpoint)
        
        return {
            'list_name': list_name,
            'item_id': item_id,
            'deleted': True,
            'recycled': recycle
        }
    
    def _get_list_schema(self, args: Dict) -> Dict:
        """Get list schema/fields."""
        list_name = args.get('list_name')
        
        endpoint = f"web/lists/getbytitle('{list_name}')/fields?$filter=Hidden eq false"
        response = self._make_request('GET', endpoint)
        
        fields = []
        for field in response.get('d', {}).get('results', []):
            fields.append({
                'name': field.get('InternalName'),
                'display_name': field.get('Title'),
                'type': field.get('TypeAsString'),
                'required': field.get('Required'),
                'read_only': field.get('ReadOnlyField'),
                'default_value': field.get('DefaultValue')
            })
        
        return {
            'list_name': list_name,
            'field_count': len(fields),
            'fields': fields
        }
    
    def _query_items(self, args: Dict) -> Dict:
        """Query list items with CAML or OData filter."""
        list_name = args.get('list_name')
        filter_query = args.get('filter')
        select_fields = args.get('select_fields', [])
        order_by = args.get('order_by')
        top = args.get('top', 100)
        
        endpoint = f"web/lists/getbytitle('{list_name}')/items"
        params = [f"$top={top}"]
        
        if filter_query:
            params.append(f"$filter={filter_query}")
        if select_fields:
            params.append(f"$select={','.join(select_fields)}")
        if order_by:
            params.append(f"$orderby={order_by}")
        
        endpoint += "?" + "&".join(params)
        response = self._make_request('GET', endpoint)
        
        items = response.get('d', {}).get('results', [])
        
        return {
            'list_name': list_name,
            'filter': filter_query,
            'item_count': len(items),
            'items': items
        }


class SharePointSiteTool(SharePointBaseTool):
    """
    SharePoint Site Operations Tool.
    
    Operations: get_site_info, get_subsites, get_users, get_groups,
    get_permissions, get_content_types
    """
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute site operation."""
        import time
        start_time = time.time()
        
        try:
            operation = arguments.get('operation', 'get_site_info')
            
            if operation == 'get_site_info':
                result = self._get_site_info()
            elif operation == 'get_subsites':
                result = self._get_subsites()
            elif operation == 'get_users':
                result = self._get_users(arguments)
            elif operation == 'get_groups':
                result = self._get_groups()
            elif operation == 'get_permissions':
                result = self._get_permissions(arguments)
            elif operation == 'get_content_types':
                result = self._get_content_types()
            else:
                return {
                    'success': False,
                    'error': f"Unknown operation: {operation}"
                }
            
            execution_time = round((time.time() - start_time) * 1000, 2)
            result['execution_time_ms'] = execution_time
            result['success'] = True
            return result
            
        except Exception as e:
            logger.error(f"SharePointSiteTool error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_site_info(self) -> Dict:
        """Get site information."""
        endpoint = "web"
        response = self._make_request('GET', endpoint)
        
        site = response.get('d', {})
        return {
            'title': site.get('Title'),
            'description': site.get('Description'),
            'url': site.get('Url'),
            'created': site.get('Created'),
            'language': site.get('Language'),
            'template': site.get('WebTemplate')
        }
    
    def _get_subsites(self) -> Dict:
        """Get subsites."""
        endpoint = "web/webs"
        response = self._make_request('GET', endpoint)
        
        subsites = []
        for site in response.get('d', {}).get('results', []):
            subsites.append({
                'title': site.get('Title'),
                'url': site.get('Url'),
                'created': site.get('Created')
            })
        
        return {
            'subsite_count': len(subsites),
            'subsites': subsites
        }
    
    def _get_users(self, args: Dict) -> Dict:
        """Get site users."""
        endpoint = "web/siteusers"
        response = self._make_request('GET', endpoint)
        
        users = []
        for user in response.get('d', {}).get('results', []):
            users.append({
                'id': user.get('Id'),
                'title': user.get('Title'),
                'email': user.get('Email'),
                'login_name': user.get('LoginName'),
                'is_site_admin': user.get('IsSiteAdmin')
            })
        
        return {
            'user_count': len(users),
            'users': users
        }
    
    def _get_groups(self) -> Dict:
        """Get site groups."""
        endpoint = "web/sitegroups"
        response = self._make_request('GET', endpoint)
        
        groups = []
        for group in response.get('d', {}).get('results', []):
            groups.append({
                'id': group.get('Id'),
                'title': group.get('Title'),
                'description': group.get('Description'),
                'owner_title': group.get('OwnerTitle')
            })
        
        return {
            'group_count': len(groups),
            'groups': groups
        }
    
    def _get_permissions(self, args: Dict) -> Dict:
        """Get permissions for an object."""
        object_url = args.get('object_url', '')
        
        if object_url:
            endpoint = f"web/GetFileByServerRelativeUrl('{object_url}')/ListItemAllFields/RoleAssignments"
        else:
            endpoint = "web/RoleAssignments"
        
        response = self._make_request('GET', endpoint)
        
        permissions = []
        for role in response.get('d', {}).get('results', []):
            permissions.append({
                'principal_id': role.get('PrincipalId'),
                'role_definition_bindings': role.get('RoleDefinitionBindings', {}).get('results', [])
            })
        
        return {
            'permission_count': len(permissions),
            'permissions': permissions
        }
    
    def _get_content_types(self) -> Dict:
        """Get site content types."""
        endpoint = "web/contenttypes"
        response = self._make_request('GET', endpoint)
        
        content_types = []
        for ct in response.get('d', {}).get('results', []):
            content_types.append({
                'id': ct.get('StringId'),
                'name': ct.get('Name'),
                'description': ct.get('Description'),
                'group': ct.get('Group')
            })
        
        return {
            'content_type_count': len(content_types),
            'content_types': content_types
        }


class SharePointSearchTool(SharePointBaseTool):
    """
    SharePoint Enterprise Search Tool.
    
    Comprehensive search across sites, documents, lists, and people.
    """
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute search operation."""
        import time
        start_time = time.time()
        
        try:
            search_type = arguments.get('search_type', 'all')
            
            if search_type == 'documents':
                result = self._search_documents(arguments)
            elif search_type == 'people':
                result = self._search_people(arguments)
            elif search_type == 'sites':
                result = self._search_sites(arguments)
            elif search_type == 'all':
                result = self._search_all(arguments)
            else:
                return {
                    'success': False,
                    'error': f"Unknown search type: {search_type}"
                }
            
            execution_time = round((time.time() - start_time) * 1000, 2)
            result['execution_time_ms'] = execution_time
            result['success'] = True
            return result
            
        except Exception as e:
            logger.error(f"SharePointSearchTool error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _search_all(self, args: Dict) -> Dict:
        """Search all content."""
        query = args.get('query', '*')
        max_results = args.get('max_results', 50)
        start_row = args.get('start_row', 0)
        
        endpoint = f"search/query?querytext='{query}'&rowlimit={max_results}&startrow={start_row}"
        response = self._make_request('GET', endpoint)
        
        return self._parse_search_results(response, query)
    
    def _search_documents(self, args: Dict) -> Dict:
        """Search documents only."""
        query = args.get('query', '*')
        file_types = args.get('file_types', [])
        max_results = args.get('max_results', 50)
        
        search_query = f"({query}) AND IsDocument:true"
        if file_types:
            type_filter = ' OR '.join([f'FileExtension:{ext}' for ext in file_types])
            search_query = f"({search_query}) AND ({type_filter})"
        
        endpoint = f"search/query?querytext='{search_query}'&rowlimit={max_results}"
        response = self._make_request('GET', endpoint)
        
        return self._parse_search_results(response, query)
    
    def _search_people(self, args: Dict) -> Dict:
        """Search people."""
        query = args.get('query', '*')
        max_results = args.get('max_results', 50)
        
        endpoint = f"search/query?querytext='{query}'&sourceid='b09a7990-05ea-4af9-81ef-edfab16c4e31'&rowlimit={max_results}"
        response = self._make_request('GET', endpoint)
        
        return self._parse_search_results(response, query)
    
    def _search_sites(self, args: Dict) -> Dict:
        """Search sites."""
        query = args.get('query', '*')
        max_results = args.get('max_results', 50)
        
        search_query = f"({query}) AND contentclass:STS_Site"
        endpoint = f"search/query?querytext='{search_query}'&rowlimit={max_results}"
        response = self._make_request('GET', endpoint)
        
        return self._parse_search_results(response, query)
    
    def _parse_search_results(self, response: Dict, query: str) -> Dict:
        """Parse search results into standard format."""
        query_result = response.get('d', {}).get('query', {})
        primary_results = query_result.get('PrimaryQueryResult', {}).get('RelevantResults', {})
        
        total_rows = primary_results.get('TotalRows', 0)
        rows = primary_results.get('Table', {}).get('Rows', {}).get('results', [])
        
        results = []
        for row in rows:
            cells = {cell['Key']: cell['Value'] for cell in row.get('Cells', {}).get('results', [])}
            results.append({
                'title': cells.get('Title'),
                'path': cells.get('Path'),
                'author': cells.get('Author'),
                'modified': cells.get('LastModifiedTime'),
                'file_type': cells.get('FileExtension'),
                'size': cells.get('Size'),
                'summary': cells.get('HitHighlightedSummary'),
                'site_name': cells.get('SiteName'),
                'content_class': cells.get('contentclass')
            })
        
        return {
            'query': query,
            'total_results': total_rows,
            'result_count': len(results),
            'results': results
        }

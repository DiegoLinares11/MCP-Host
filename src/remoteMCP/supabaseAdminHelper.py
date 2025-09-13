#!/usr/bin/env python3
"""
Servidor MCP Remoto - Supabase Admin Helper (Real)
Implementa operaciones administrativas reales contra la API de Supabase
"""
import json
import uuid
import os
import requests
from typing import Dict, Any, List, Optional
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import re

from pathlib import Path
from dotenv import load_dotenv

# sube dos niveles desde este archivo
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path, override=True)


app = Flask(__name__)
CORS(app)

class MCPSupabaseServer:
    def __init__(self):
        self.capabilities = {
            "tools": {}
        }
        
        # Configuración real de Supabase desde variables de entorno
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        self.anon_key = os.getenv("SUPABASE_ANON_KEY")
        
        if not self.supabase_url or not self.service_key:
            raise ValueError("SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY son requeridas")
        
        # URLs de la API
        self.auth_url = f"{self.supabase_url}/auth/v1"
        self.rest_url = f"{self.supabase_url}/rest/v1"
        
        # Headers para requests administrativos (con service role)
        self.admin_headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json"
        }
        
        # Headers para requests de usuario normal
        self.user_headers = {
            "apikey": self.anon_key or self.service_key,
            "Authorization": f"Bearer {self.anon_key or self.service_key}",
            "Content-Type": "application/json"
        }
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Lista de tools administrativas disponibles"""
        return [
            {
                "name": "create_user",
                "description": "Crea un nuevo usuario en Supabase Auth",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Email del usuario"
                        },
                        "password": {
                            "type": "string",
                            "description": "Contraseña del usuario"
                        },
                        "user_metadata": {
                            "type": "object",
                            "description": "Metadata del usuario (nombre, rol, etc.)",
                            "default": {}
                        },
                        "email_confirm": {
                            "type": "boolean",
                            "description": "Si confirmar automáticamente el email",
                            "default": True
                        }
                    },
                    "required": ["email", "password"]
                }
            },
            {
                "name": "send_magic_link",
                "description": "Envía un magic link de autenticación por email",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Email del destinatario"
                        },
                        "redirect_to": {
                            "type": "string",
                            "description": "URL de redirección después del login",
                            "default": ""
                        }
                    },
                    "required": ["email"]
                }
            },
            {
                "name": "list_users",
                "description": "Lista usuarios registrados con paginación",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "integer",
                            "description": "Número de página",
                            "default": 1
                        },
                        "per_page": {
                            "type": "integer",
                            "description": "Usuarios por página (máximo 1000)",
                            "default": 50
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "get_user_by_id",
                "description": "Obtiene información de un usuario específico",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "UUID del usuario"
                        }
                    },
                    "required": ["user_id"]
                }
            },
            {
                "name": "update_user_metadata",
                "description": "Actualiza metadata de un usuario",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "UUID del usuario"
                        },
                        "user_metadata": {
                            "type": "object",
                            "description": "Nueva metadata del usuario"
                        },
                        "app_metadata": {
                            "type": "object",
                            "description": "Metadata de aplicación (roles, etc.)",
                            "default": {}
                        }
                    },
                    "required": ["user_id", "user_metadata"]
                }
            },
            {
                "name": "delete_user",
                "description": "Elimina un usuario (acción irreversible)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "UUID del usuario a eliminar"
                        }
                    },
                    "required": ["user_id"]
                }
            },
            {
                "name": "get_user_stats",
                "description": "Obtiene estadísticas de usuarios desde la API",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_totals": {
                            "type": "boolean",
                            "description": "Incluir totales generales",
                            "default": True
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "bulk_invite_users",
                "description": "Invita múltiples usuarios enviando magic links",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "emails": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Lista de emails para invitar"
                        },
                        "redirect_to": {
                            "type": "string",
                            "description": "URL de redirección para todos los invitados",
                            "default": ""
                        }
                    },
                    "required": ["emails"]
                }
            },
            {
                "name": "reset_user_password",
                "description": "Envía email de reset de contraseña a un usuario",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Email del usuario"
                        },
                        "redirect_to": {
                            "type": "string",
                            "description": "URL de redirección después del reset",
                            "default": ""
                        }
                    },
                    "required": ["email"]
                }
            }
        ]
    
    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta una herramienta administrativa"""
        try:
            if name == "create_user":
                return self._create_user(arguments)
            elif name == "send_magic_link":
                return self._send_magic_link(arguments)
            elif name == "list_users":
                return self._list_users(arguments)
            elif name == "get_user_by_id":
                return self._get_user_by_id(arguments)
            elif name == "update_user_metadata":
                return self._update_user_metadata(arguments)
            elif name == "delete_user":
                return self._delete_user(arguments)
            elif name == "get_user_stats":
                return self._get_user_stats(arguments)
            elif name == "bulk_invite_users":
                return self._bulk_invite_users(arguments)
            elif name == "reset_user_password":
                return self._reset_user_password(arguments)
            else:
                return {
                    "content": [{"type": "text", "text": f"Tool '{name}' no encontrada"}],
                    "isError": True
                }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error ejecutando {name}: {str(e)}"}],
                "isError": True
            }
    
    def _create_user(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Crea un nuevo usuario usando Admin API"""
        email = args.get("email", "")
        password = args.get("password", "")
        user_metadata = args.get("user_metadata", {})
        email_confirm = args.get("email_confirm", True)
        
        if not email or not password:
            return {
                "content": [{"type": "text", "text": "Email y contraseña son requeridos"}],
                "isError": True
            }
        
        payload = {
            "email": email,
            "password": password,
            "user_metadata": user_metadata,
            "email_confirm": email_confirm
        }
        
        try:
            response = requests.post(
                f"{self.auth_url}/admin/users",
                json=payload,
                headers=self.admin_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                user_data = response.json()
                result = f"✅ Usuario creado exitosamente\n"
                result += f"ID: {user_data.get('id')}\n"
                result += f"Email: {user_data.get('email')}\n"
                result += f"Confirmado: {'Sí' if user_data.get('email_confirmed_at') else 'No'}\n"
                result += f"Creado: {user_data.get('created_at')}\n"
                if user_metadata:
                    result += f"Metadata: {json.dumps(user_metadata, indent=2)}"
                
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False,
                    "structuredContent": {"result": user_data}
                }
            else:
                error_msg = response.json().get('msg', 'Error desconocido')
                return {
                    "content": [{"type": "text", "text": f"❌ Error creando usuario: {error_msg}"}],
                    "isError": True
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"❌ Error de conexión: {str(e)}"}],
                "isError": True
            }
    
    def _send_magic_link(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Envía magic link usando Auth API"""
        email = args.get("email", "")
        redirect_to = args.get("redirect_to", "")
        
        if not email:
            return {
                "content": [{"type": "text", "text": "Email es requerido"}],
                "isError": True
            }
        
        payload = {"email": email}
        if redirect_to:
            payload["options"] = {"redirect_to": redirect_to}
        
        try:
            response = requests.post(
                f"{self.auth_url}/magiclink",
                json=payload,
                headers=self.user_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = f"📧 Magic link enviado a {email}\n"
                result += f"Estado: Enviado exitosamente\n"
                if redirect_to:
                    result += f"Redirección: {redirect_to}\n"
                result += f"Válido por: 1 hora"
                
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False
                }
            else:
                error_msg = response.json().get('msg', 'Error desconocido')
                return {
                    "content": [{"type": "text", "text": f"❌ Error enviando magic link: {error_msg}"}],
                    "isError": True
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"❌ Error de conexión: {str(e)}"}],
                "isError": True
            }
    
    def _list_users(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Lista usuarios usando Admin API"""
        page = max(1, args.get("page", 1))
        per_page = min(1000, max(1, args.get("per_page", 50)))
        
        try:
            response = requests.get(
                f"{self.auth_url}/admin/users",
                params={"page": page, "per_page": per_page},
                headers=self.admin_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                users = data.get("users", [])
                
                result = f"👥 Lista de usuarios (Página {page})\n\n"
                result += f"Total en esta página: {len(users)}\n"
                result += f"Usuarios por página: {per_page}\n\n"
                
                for i, user in enumerate(users, 1):
                    result += f"{i}. {user.get('email')} (ID: {user.get('id')[:8]}...)\n"
                    result += f"   Creado: {user.get('created_at', 'N/A')[:10]}\n"
                    result += f"   Confirmado: {'Sí' if user.get('email_confirmed_at') else 'No'}\n"
                    if user.get('user_metadata'):
                        metadata = user.get('user_metadata', {})
                        if metadata:
                            result += f"   Metadata: {json.dumps(metadata)}\n"
                    result += "\n"
                
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False,
                    "structuredContent": {"result": data}
                }
            else:
                error_msg = response.json().get('msg', 'Error desconocido')
                return {
                    "content": [{"type": "text", "text": f"❌ Error listando usuarios: {error_msg}"}],
                    "isError": True
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"❌ Error de conexión: {str(e)}"}],
                "isError": True
            }
    
    def _get_user_by_id(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Obtiene un usuario específico por ID"""
        user_id = args.get("user_id", "")
        
        if not user_id:
            return {
                "content": [{"type": "text", "text": "user_id es requerido"}],
                "isError": True
            }
        
        try:
            response = requests.get(
                f"{self.auth_url}/admin/users/{user_id}",
                headers=self.admin_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                user = response.json()
                result = f"👤 Información del usuario\n\n"
                result += f"ID: {user.get('id')}\n"
                result += f"Email: {user.get('email')}\n"
                result += f"Confirmado: {'Sí' if user.get('email_confirmed_at') else 'No'}\n"
                result += f"Creado: {user.get('created_at')}\n"
                result += f"Última conexión: {user.get('last_sign_in_at', 'Nunca')}\n"
                
                if user.get('user_metadata'):
                    result += f"Metadata usuario:\n{json.dumps(user.get('user_metadata'), indent=2)}\n"
                
                if user.get('app_metadata'):
                    result += f"Metadata app:\n{json.dumps(user.get('app_metadata'), indent=2)}\n"
                
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False,
                    "structuredContent": {"result": user}
                }
            else:
                error_msg = response.json().get('msg', 'Usuario no encontrado')
                return {
                    "content": [{"type": "text", "text": f"❌ Error obteniendo usuario: {error_msg}"}],
                    "isError": True
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"❌ Error de conexión: {str(e)}"}],
                "isError": True
            }
    
    def _update_user_metadata(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Actualiza metadata de un usuario"""
        user_id = args.get("user_id", "")
        user_metadata = args.get("user_metadata", {})
        app_metadata = args.get("app_metadata", {})
        
        if not user_id:
            return {
                "content": [{"type": "text", "text": "user_id es requerido"}],
                "isError": True
            }
        
        payload = {}
        if user_metadata:
            payload["user_metadata"] = user_metadata
        if app_metadata:
            payload["app_metadata"] = app_metadata
            
        if not payload:
            return {
                "content": [{"type": "text", "text": "Se requiere user_metadata o app_metadata"}],
                "isError": True
            }
        
        try:
            response = requests.put(
                f"{self.auth_url}/admin/users/{user_id}",
                json=payload,
                headers=self.admin_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                user = response.json()
                result = f"✅ Metadata actualizada exitosamente\n"
                result += f"Usuario: {user.get('email')} ({user_id[:8]}...)\n"
                result += f"Actualizado: {datetime.now().isoformat()}\n"
                
                if user_metadata:
                    result += f"Nueva metadata usuario:\n{json.dumps(user_metadata, indent=2)}\n"
                if app_metadata:
                    result += f"Nueva metadata app:\n{json.dumps(app_metadata, indent=2)}"
                
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False,
                    "structuredContent": {"result": user}
                }
            else:
                error_msg = response.json().get('msg', 'Error desconocido')
                return {
                    "content": [{"type": "text", "text": f"❌ Error actualizando usuario: {error_msg}"}],
                    "isError": True
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"❌ Error de conexión: {str(e)}"}],
                "isError": True
            }
    
    def _delete_user(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Elimina un usuario (acción irreversible)"""
        user_id = args.get("user_id", "")
        
        if not user_id:
            return {
                "content": [{"type": "text", "text": "user_id es requerido"}],
                "isError": True
            }
        
        try:
            response = requests.delete(
                f"{self.auth_url}/admin/users/{user_id}",
                headers=self.admin_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = f"🗑️ Usuario eliminado exitosamente\n"
                result += f"ID eliminado: {user_id}\n"
                result += f"Fecha: {datetime.now().isoformat()}\n"
                result += f"⚠️ Esta acción es irreversible"
                
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False
                }
            else:
                error_msg = response.json().get('msg', 'Error desconocido')
                return {
                    "content": [{"type": "text", "text": f"❌ Error eliminando usuario: {error_msg}"}],
                    "isError": True
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"❌ Error de conexión: {str(e)}"}],
                "isError": True
            }
    
    def _get_user_stats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Obtiene estadísticas reales consultando usuarios"""
        try:
            # Obtener todos los usuarios (primera página con límite alto)
            response = requests.get(
                f"{self.auth_url}/admin/users",
                params={"per_page": 1000},
                headers=self.admin_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                users = data.get("users", [])
                
                total = len(users)
                confirmed = sum(1 for u in users if u.get('email_confirmed_at'))
                unconfirmed = total - confirmed
                
                # Estadísticas por fecha
                now = datetime.now()
                today = now.date()
                week_ago = (now - timedelta(days=7)).date()
                month_ago = (now - timedelta(days=30)).date()
                
                today_count = 0
                week_count = 0
                month_count = 0
                
                for user in users:
                    created_str = user.get('created_at', '')
                    if created_str:
                        try:
                            created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00')).date()
                            if created_date >= today:
                                today_count += 1
                            if created_date >= week_ago:
                                week_count += 1
                            if created_date >= month_ago:
                                month_count += 1
                        except:
                            pass
                
                result = f"📊 Estadísticas de usuarios reales\n\n"
                result += f"Total de usuarios: {total}\n"
                result += f"Confirmados: {confirmed}\n"
                result += f"Sin confirmar: {unconfirmed}\n\n"
                result += f"Registros hoy: {today_count}\n"
                result += f"Registros esta semana: {week_count}\n"
                result += f"Registros este mes: {month_count}\n\n"
                result += f"Tasa de confirmación: {(confirmed/total*100):.1f}%" if total > 0 else "0%"
                
                stats_data = {
                    "total": total,
                    "confirmed": confirmed,
                    "unconfirmed": unconfirmed,
                    "today": today_count,
                    "week": week_count,
                    "month": month_count,
                    "confirmation_rate": confirmed/total*100 if total > 0 else 0
                }
                
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False,
                    "structuredContent": {"result": stats_data}
                }
            else:
                error_msg = response.json().get('msg', 'Error desconocido')
                return {
                    "content": [{"type": "text", "text": f"❌ Error obteniendo estadísticas: {error_msg}"}],
                    "isError": True
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"❌ Error de conexión: {str(e)}"}],
                "isError": True
            }
    
    def _bulk_invite_users(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Invita múltiples usuarios enviando magic links"""
        emails = args.get("emails", [])
        redirect_to = args.get("redirect_to", "")
        
        if not emails or not isinstance(emails, list):
            return {
                "content": [{"type": "text", "text": "Se requiere una lista de emails"}],
                "isError": True
            }
        
        successful = []
        failed = []
        
        for email in emails:
            if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
                failed.append({"email": email, "reason": "Email inválido"})
                continue
            
            try:
                payload = {"email": email}
                if redirect_to:
                    payload["options"] = {"redirect_to": redirect_to}
                
                response = requests.post(
                    f"{self.auth_url}/magiclink",
                    json=payload,
                    headers=self.user_headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    successful.append({
                        "email": email,
                        "invited_at": datetime.now().isoformat(),
                        "status": "sent"
                    })
                else:
                    error_msg = response.json().get('msg', 'Error desconocido')
                    failed.append({"email": email, "reason": error_msg})
                    
            except requests.exceptions.RequestException as e:
                failed.append({"email": email, "reason": f"Error de conexión: {str(e)}"})
        
        result = f"📬 Invitaciones masivas completadas\n\n"
        result += f"✅ Exitosas: {len(successful)}\n"
        result += f"❌ Fallidas: {len(failed)}\n"
        if redirect_to:
            result += f"URL redirección: {redirect_to}\n"
        result += "\n"
        
        if successful:
            result += "Invitaciones exitosas:\n"
            for inv in successful[:5]:  # Mostrar solo primeras 5
                result += f"  ✓ {inv['email']}\n"
            if len(successful) > 5:
                result += f"  ... y {len(successful) - 5} más\n"
            result += "\n"
        
        if failed:
            result += "Invitaciones fallidas:\n"
            for fail in failed:
                result += f"  ✗ {fail['email']}: {fail['reason']}\n"
        
        return {
            "content": [{"type": "text", "text": result}],
            "isError": False,
            "structuredContent": {
                "result": {
                    "successful": successful,
                    "failed": failed,
                    "total_sent": len(successful),
                    "total_failed": len(failed)
                }
            }
        }
    
    def _reset_user_password(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Envía email de reset de contraseña"""
        email = args.get("email", "")
        redirect_to = args.get("redirect_to", "")
        
        if not email:
            return {
                "content": [{"type": "text", "text": "Email es requerido"}],
                "isError": True
            }
        
        payload = {"email": email}
        if redirect_to:
            payload["options"] = {"redirect_to": redirect_to}
        
        try:
            response = requests.post(
                f"{self.auth_url}/recover",
                json=payload,
                headers=self.user_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = f"🔐 Email de reset enviado a {email}\n"
                result += f"Estado: Enviado exitosamente\n"
                if redirect_to:
                    result += f"Redirección: {redirect_to}\n"
                result += f"Válido por: 1 hora"
                
                return {
                    "content": [{"type": "text", "text": result}],
                    "isError": False
                }
            else:
                error_msg = response.json().get('msg', 'Error desconocido')
                return {
                    "content": [{"type": "text", "text": f"❌ Error enviando reset: {error_msg}"}],
                    "isError": True
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "content": [{"type": "text", "text": f"❌ Error de conexión: {str(e)}"}],
                "isError": True
            }

# Instancia global del servidor
mcp_server = MCPSupabaseServer()

@app.route('/mcp', methods=['POST'])
def handle_mcp():
    """Endpoint principal para requests MCP via JSON-RPC"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        if data.get("jsonrpc") != "2.0":
            return jsonify({"error": "Invalid JSON-RPC version"}), 400

        method = data.get("method", "")
        params = data.get("params", {}) or {}
        req_id = data.get("id")

        if method == "initialize":
            return jsonify({
                "jsonrpc":"2.0","id":req_id,
                "result":{
                    "protocolVersion":"2024-11-05",
                    "capabilities": mcp_server.capabilities,
                    "serverInfo":{"name":"supabase-admin-mcp-server","version":"1.0.0"}
                }
            })

        elif method == "tools/list":
            tools = mcp_server.get_tools()
            return jsonify({"jsonrpc":"2.0","id":req_id,"result":{"tools":tools}})

        elif method == "tools/call":
            name = params.get("name","")
            arguments = params.get("arguments",{}) or {}
            res = mcp_server.call_tool(name, arguments)
            return jsonify({"jsonrpc":"2.0","id":req_id,"result":res})

        elif method == "notifications/initialized":
            return ("", 204)

        else:
            return jsonify({"jsonrpc":"2.0","id":req_id,
                            "error":{"code":-32601,"message":f"Method not found: {method}"}}), 400

    except Exception as e:
        return jsonify({"jsonrpc":"2.0","id": data.get("id") if isinstance(data,dict) else None,
                        "error":{"code":-32603,"message":f"Internal error: {e}"}}), 500
    
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "service": "supabase-admin-mcp-server"})

@app.route('/', methods=['GET'])
def info():
    return jsonify({
        "name": "Supabase Admin MCP Server",
        "version": "1.0.0",
        "protocol": "MCP over HTTP",
        "endpoint": "/mcp",
        "tools": [tool["name"] for tool in mcp_server.get_tools()]
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)

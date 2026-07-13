from flask import jsonify
from flask_jwt_extended import get_jwt, jwt_required
from functools import wraps

def rol_required(rol):
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def decorator(*args, **kwargs):
            claims = get_jwt()
            if claims.get("rol") != rol:
                return jsonify({"error": "No tienes permisos para esta acción"}), 403
            return fn(*args, **kwargs)
        return decorator
    return wrapper

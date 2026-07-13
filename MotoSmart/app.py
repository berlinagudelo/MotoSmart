from datetime import timedelta

from flask import render_template
from flask_jwt_extended import JWTManager

from db import db, app
from router.auth import auth_bp
from router.citas import citas_bp
from router.clientes import clientes_bp
from router.motos import motos_bp
from router.scanner import scanner_bp

app.config['JWT_SECRET_KEY'] = 'b7f9c2d8e4a1f6d3c9b0a7e2f5d4c8b1a6e3f9d7c2b8a0f4d5c7e9a2b1f8c3d6'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
jwt = JWTManager(app)

@app.route('/')
def home():
    return render_template('index.html')

app.register_blueprint(citas_bp)
app.register_blueprint(motos_bp)
app.register_blueprint(clientes_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(scanner_bp)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

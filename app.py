"""
NoteShare application entry point.

Creating the app does not connect to MySQL; a connection is made the first
time the database is actually used.

Development server:
    flask --app app run --debug
or
    python app.py
"""

import os

from flask import Flask, redirect, render_template, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

import auth
from config import Config
from models import db

csrf = CSRFProtect()

ERROR_PAGES = {
    400: ("Bad request", "The request could not be understood. Go back, reload the page and try again."),
    403: ("Access denied", "Your account does not have permission to view this page."),
    404: ("Page not found", "The page you asked for does not exist or has moved."),
    405: ("Method not allowed", "This page cannot be opened that way."),
    500: ("Something went wrong", "An unexpected error occurred. Please try again in a moment."),
}


def _error_page(code, message=None):
    title, default_message = ERROR_PAGES[code]
    return render_template("error.html", code=code, title=title,
                           message=message or default_message), code


def create_app(config_class=Config) -> Flask:
    config_class.validate()

    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)  # every POST must carry a valid csrf_token
    app.register_blueprint(auth.bp)

    @app.route("/")
    def index():
        # There is no homepage yet: send visitors to the right starting point.
        if auth.get_current_user() is not None:
            return redirect(url_for(auth.DEFAULT_ENDPOINT))
        return redirect(url_for("auth.login"))

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        return _error_page(400, "This form has expired or did not come from NoteShare. "
                                "Go back, reload the page and try again.")

    for code in (403, 404, 405):
        app.register_error_handler(code, lambda error, code=code: _error_page(code))

    @app.errorhandler(500)
    def handle_server_error(error):
        db.session.rollback()
        return _error_page(500)

    return app


if __name__ == "__main__":
    # Development server only; never use it in production.
    create_app().run()

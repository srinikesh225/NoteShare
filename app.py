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

from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect

import admin
import auth
import moderation
import notes
import seo
from config import Config
from models import db

csrf = CSRFProtect()

ERROR_PAGES = {
    400: ("Bad request", "The request could not be understood. Go back, reload the page and try again."),
    403: ("Access denied", "Your account does not have permission to view this page."),
    404: ("Page not found", "The page you asked for does not exist or has moved."),
    405: ("Method not allowed", "This page cannot be opened that way."),
    413: ("File too large", "The upload is larger than the 10 MiB limit."),
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
    app.register_blueprint(notes.bp)
    app.register_blueprint(seo.bp)
    app.register_blueprint(moderation.bp)
    app.register_blueprint(admin.bp)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        return _error_page(400, "This form has expired or did not come from NoteShare. "
                                "Go back, reload the page and try again.")

    def handle_http_error(error):
        # Show a message passed with abort(code, description=...), but never
        # Werkzeug's generic default text.
        custom = error.description if error.description != type(error).description else None
        return _error_page(error.code, custom)

    for code in (403, 404, 405):
        app.register_error_handler(code, handle_http_error)

    @app.errorhandler(413)
    def handle_too_large(error):
        # Raised by Werkzeug before the view runs when a request is larger
        # than MAX_CONTENT_LENGTH, so the submitted form values are not
        # available; show the upload form again with a file error.
        if request.endpoint == "notes.upload" and auth.get_current_user() is not None:
            return notes.render_upload_form(
                errors={"file": "This file is larger than the 10 MiB limit. Choose a smaller file."},
                status=413)
        return _error_page(413)

    @app.errorhandler(500)
    def handle_server_error(error):
        db.session.rollback()
        return _error_page(500)

    return app


if __name__ == "__main__":
    # Development server only; never use it in production.
    create_app().run()

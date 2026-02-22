"""Web dashboard for PolySuite."""
from flask import Flask, render_template
from flask_socketio import SocketIO
from src.wallet.storage import WalletStorage


class Dashboard:
    """Web dashboard for PolySuite."""

    def __init__(self, storage: WalletStorage, socketio: SocketIO):
        """Initialize the dashboard."""
        self.app = Flask(__name__)
        self.socketio = socketio
        self.storage = storage

        # Attach the app to the socketio instance
        self.socketio.init_app(self.app)

        @self.app.route("/")
        def index():
            wallets = self.storage.list_wallets()
            return render_template("index.html", wallets=wallets)

        @self.socketio.on("connect")
        def handle_connect():
            """Handle a client connection."""
            print("Client connected")

    def run(self):
        """Run the dashboard."""
        self.socketio.run(self.app, debug=True)

import sys
import os
import subprocess
import time
import socket
import signal
from PyQt6.QtCore import QUrl, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QProgressBar, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView

# Configuration
PORT = 8000
SERVER_URL = f"http://127.0.0.1:{PORT}"

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

class ServerWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.process = None

    def run(self):
        # Determine the base directory of the backend
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Start uvicorn server in a subprocess
        try:
            env = os.environ.copy()
            # Ensure the python path contains the base directory
            env["PYTHONPATH"] = base_dir + os.pathsep + env.get("PYTHONPATH", "")
            
            self.process = subprocess.Popen(
                ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
                cwd=base_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait until server is reachable
            attempts = 0
            while attempts < 30:
                if is_port_in_use(PORT):
                    self.finished.emit()
                    return
                time.sleep(0.5)
                attempts += 1
                
            self.error.emit("Timeout waiting for POS backend server to start.")
        except Exception as e:
            self.error.emit(f"Failed to start backend server: {str(e)}")

    def terminate_server(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("POS Billing & Management System")
        self.resize(1280, 800)

        # Set up UI layouts
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Progress/Loading Label and Bar
        self.loading_label = QLabel("Initializing POS system backend...", self)
        self.loading_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #4F46E5; margin: 10px;")
        self.layout.addWidget(self.loading_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0) # Indeterminate progress
        self.progress_bar.setStyleSheet("QProgressBar { border: 2px solid #E5E7EB; border-radius: 5px; height: 15px; } QProgressBar::chunk { background-color: #4F46E5; }")
        self.layout.addWidget(self.progress_bar)

        # Start Server Worker Thread
        self.worker = ServerWorker()
        self.worker.finished.connect(self.on_server_ready)
        self.worker.error.connect(self.on_server_error)
        self.worker.start()

    def on_server_ready(self):
        # Remove loading indicators
        self.layout.removeWidget(self.loading_label)
        self.layout.removeWidget(self.progress_bar)
        self.loading_label.deleteLater()
        self.progress_bar.deleteLater()

        # Initialize web view
        self.web_view = QWebEngineView(self)
        self.layout.addWidget(self.web_view)
        self.web_view.load(QUrl(SERVER_URL))
        self.web_view.titleChanged.connect(self.setWindowTitle)

    def on_server_error(self, message):
        self.loading_label.setText(f"Error: {message}")
        self.progress_bar.hide()

    def closeEvent(self, event):
        # Cleanly stop backend server on exit
        self.worker.terminate_server()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

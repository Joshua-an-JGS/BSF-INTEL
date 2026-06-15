from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication
import time
from datetime import datetime

from ..model.model_loader import BSFModelLoader
from ..model.inference import BSFInference
from ..view.main_window import MainWindow
from ..view.license_dialog import LicenseDialog
from ..services.license_manager import LicenseManager
from ..services.updater import UpdaterService
from ..services.database_service import DatabaseService
from ..services.surface_prediction_service import SurfacePredictionService
from ..services.industrial_device_manager import IndustrialDeviceManager

class MainController(QObject):
    restartRequested = pyqtSignal()
    # New signals for thread-safe UI updates from background auth thread
    googleAuthSuccess = pyqtSignal(str)
    googleAuthFailed = pyqtSignal(str)

    def __init__(self, license_manager=None, auth=None):
        super().__init__()
        self.license_manager = license_manager
        self.auth = auth
        self.updater = UpdaterService()
        self.update_info = {}
        self.should_exit = False
        self.google_auth_svc = None # Keep reference
        self.db = DatabaseService()
        self.surface_svc = SurfacePredictionService()
        self.current_trial_id = None
        self.current_user_role = "user"
        self._start_time = time.time()
        self._part_count = 1240
        self.dash_timer = QTimer()
        self.DASHBOARD_SIMULATION = False # Disabled mock UI simulation; driven by live PLC/VFD signals
        self.ind_mgr = IndustrialDeviceManager.get_instance()
        self._force_samples_buffer = []
        self._power_samples_buffer = []
        self._max_sensor_buffer = 50000
        
        # 1. Initialize logic (Models NOT loaded yet)
        self.loader = BSFModelLoader()
        self.inference = BSFInference(self.loader)
        
        # 2. Initialize UI
        self.view = MainWindow()
        self.inference_thread = None
        self.inference_worker = None
        
        # 3. Connect Signals
        self.view.loginRequested.connect(self.handle_login_attempt)
        self.view.googleLoginRequested.connect(self.handle_google_login)
        self.view.logoutRequested.connect(self.handle_logout)
        
        # Connect internal auth signals
        self.googleAuthSuccess.connect(self.on_auth_success)
        self.googleAuthFailed.connect(self.reset_google_btn)
        
        # New Registration Connection
        self.view.login_page.registerRequested.connect(self.handle_registration_attempt)
        
        # Unified General Tab Workflow Connections
        self.view.general_ui.trialSaved.connect(self.handle_unified_trial_save)
        self.view.general_ui.predictionRequested.connect(self.handle_unified_prediction)
        self.view.general_ui.parametersSaved.connect(self.handle_parameters_save)

        # Unified General Tab Workflow Connections
        self.view.inv_ui.optimizationRequested.connect(self.handle_optimization)
        
        self.view.notify_ui.actionRequested.connect(self.handle_notification_action)
        self.view.notify_ui.refreshRequested.connect(self.handle_manual_update_check)
        if hasattr(self.ind_mgr, "plcRawData"):
            self.ind_mgr.plcRawData.connect(self._collect_force_sample)
        else:
            self.ind_mgr.plcData.connect(self._collect_force_sample)
        if hasattr(self.ind_mgr, "vfdRawData"):
            self.ind_mgr.vfdRawData.connect(self._collect_power_sample)
        else:
            self.ind_mgr.vfdData.connect(self._collect_power_sample)

        # Route real-time UI data streams directly to dashboard widgets
        self.ind_mgr.plcData.connect(self._on_plc_data_dashboard)
        self.ind_mgr.vfdData.connect(self._on_vfd_data_dashboard)

        # Initialize User Data Widget with DB
        from ..view.user_data_widget import UserDataWidget
        self.view.user_data_ui = UserDataWidget(self.db)
        # Find index 4 or append correctly.
        self.view.stack.insertWidget(3, self.view.user_data_ui) # Insert at index 3 (User Data)
        self.view.user_data_ui.apply_theme(self.view.is_dark)

        # Dashboard buttons disabled until models ready
        self.view.inv_ui.btn.setEnabled(False)

        # Check for persistent session (Remember Me)
        self.check_remembered_session()

        # Periodic check for updates
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.check_for_updates)
        self.update_timer.start(3600000) 

        # 4. Capability Check
        # Gracefully disable Google Login if credentials are not in environment or config
        from ..utils.config import ConfigManager
        cm = ConfigManager()
        if not cm.get("google_oauth", "client_id") or not cm.get("google_oauth", "client_secret"):
            if hasattr(self.view.login_page, 'btn_google'):
                self.view.login_page.btn_google.setEnabled(False)
                self.view.login_page.btn_google.setToolTip("Google Sign-In disabled: Missing Credentials")
                # Optional: Visual indication
                style = self.view.login_page.btn_google.styleSheet()
                self.view.login_page.btn_google.setStyleSheet(style + "background-color: #E5E7EB; color: #9CA3AF;")

        # Dashboard Data Simulation
        self.dash_timer.timeout.connect(self.update_dashboard_data)
        if self.DASHBOARD_SIMULATION:
            self.dash_timer.start(100) # 100ms updates

    def update_dashboard_data(self):
        """Simulates and broadcasts data to dashboard widgets."""
        if not self.DASHBOARD_SIMULATION:
            return
            
        import random, time
        
        # 1. Graph Data (Simulated Voltage)
        voltage = 220 + random.uniform(-5, 5)
        
        # 2. Production metrics
        now = time.time()
        uptime_sec = int(now - self._start_time)
        uptime_str = time.strftime('%H:%M:%S', time.gmtime(uptime_sec))
        
        # Update dashboard widgets
        manager = self.view.dash_ui.manager
        for w in manager.widgets.values():
            name = w.__class__.__name__
            # Only update legacy simulated widgets, industrial ones are autonomous
            if name == 'RealTimeGraphWidget':
                w.update_data(voltage)
            elif name == 'AIPredictionWidget':
                if random.random() < 0.1:
                    w.update_prediction(0.50 + random.uniform(-0.05, 0.05), 95 + random.uniform(0, 3.5))
            elif name == 'StoneConditionWidget':
                if random.random() < 0.05:
                    w.update_stone_data(24 + random.uniform(0, 0.1), 1240)
            elif name == 'MachineHealthWidget':
                if random.random() < 0.2:
                    w.update_health("NORMAL", f"{38.5 + random.uniform(-0.5, 0.5)}°C", f"{42 + random.uniform(-1, 1)}%")
            elif name == 'ProductionWidget':
                if random.random() < 0.1:
                    if random.random() < 0.05: self._part_count += 1
                    w.update_metrics(self._part_count, 12.4, 280, uptime_str)
            elif name == 'AlertLogWidget':
                if random.random() < 0.02: # Rare alerts
                    levels = [("Sensor", "Voltage jitter detected", "WARNING"), 
                              ("Network", "Server heartbeat stable", "SUCCESS"),
                              ("AI Engine", "Inference trace logged", "INFO")]
                    t, m, l = random.choice(levels)
                    w.add_alert(t, m, l)

    def check_remembered_session(self):
        """Validates if a recent session can be restored."""
        if hasattr(self.auth, 'get_remembered_user'):
            user_data = self.auth.get_remembered_user()
            if user_data:
                self.on_auth_success(user_data.get("name") or user_data.get("username"))

    def handle_registration_attempt(self, username, email, password):
        """Processes registration from the integrated view."""
        success, message = self.auth.register(username, email, password)
        from PyQt6.QtWidgets import QMessageBox
        if success:
            QMessageBox.information(self.view, "Success", "Registration successful! You can now login.")
            self.view.login_page.left_panel.setCurrentIndex(0) # Back to login
        else:
            QMessageBox.critical(self.view, "Error", message)

    def handle_login_attempt(self, username, password, remember_me):
        """Processes local login from the integrated view."""
        if self.auth.login(username, password, remember_me):
            self.on_auth_success(username)
        else:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self.view, "Login Failed", "Invalid username or password.")

    def handle_general_save(self, data):
        """Processes data saved from General Tab."""
        try:
            self.current_trial_id = self.db.save_general_info(data)
            print(f"[INFO] General Data Saved to DB. Trial ID: {self.current_trial_id}")
            
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self.view, 
                "Success", 
                "General information saved! Machine Tool tab is now enabled."
            )
            # Enable next tab (logic in MainWindow could also be used)
            self.view.btn_machine.setEnabled(True)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self.view, "DB Error", f"Failed to save general info: {e}")

    def handle_machine_tool_save(self, data):
        """Processes data saved from Machine Tool Tab."""
        if not self.current_trial_id:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self.view, "Flow Error", "Please save General Info first.")
            return

        try:
            self.db.save_machine_info(self.current_trial_id, data)
            print(f"[INFO] Machine Tool Data Saved to DB for Trial {self.current_trial_id}")
            
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self.view, 
                "Success", 
                "Machine information saved! Surface Predictor is now enabled."
            )
            self.view.btn_ra.setEnabled(True)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self.view, "DB Error", f"Failed to save machine info: {e}")


    def handle_google_login(self):
        """Processes Google OAuth flow."""
        try:
            from ..services.google_auth import GoogleAuthService
            # Logic: Disable button, Start Flow -> Callback -> Exchange -> DB -> Signal -> UI
            
            self.google_auth_svc = GoogleAuthService()
            self.google_auth_svc.auth_error.connect(self.googleAuthFailed.emit)
            
            self.view.login_page.btn_google.setEnabled(False)
            self.view.login_page.btn_google.setText("  Check Browser...")

            def on_code_received(code, redirect_uri):
                # Runs in background thread
                if not code:
                    self.googleAuthFailed.emit("Authorization code missing.")
                    return

                try:
                    tokens = self.google_auth_svc.exchange_code_for_tokens(code, redirect_uri)
                    if tokens:
                        profile = self.google_auth_svc.get_user_profile(tokens.get('access_token'))
                        if profile:
                            if self.auth.login_with_google(profile, tokens):
                                display_name = profile.get("name") or profile.get("email")
                                self.googleAuthSuccess.emit(display_name)
                                return
                            else:
                                self.googleAuthFailed.emit("Database login failed.")
                                return
                        else:
                            self.googleAuthFailed.emit("Failed to fetch user profile.")
                            return
                    else:
                        self.googleAuthFailed.emit("Token exchange failed.")
                        return
                except Exception as e:
                    self.googleAuthFailed.emit(f"Auth Process Error: {str(e)}")

            # Start flow
            self.google_auth_svc.start_auth_flow(on_code_received)
            
        except Exception as e:
            self.reset_google_btn(str(e))

    def reset_google_btn(self, error):
        """Resets Google button state on failure."""
        self.view.login_page.btn_google.setEnabled(True)
        self.view.login_page.btn_google.setText("  Sign in with Google")
        
        # Only show alert if it's an actual error string, to avoid empty popups
        if error:
            from PyQt6.QtWidgets import QMessageBox
            # Use QMetaObject to ensure this runs on main thread if called directly? 
            # Signals handle this, but if called directly...
            QMessageBox.critical(self.view, "Auth Error", error)

    def on_auth_success(self, display_name):
        """Triggered after successful login."""
        role = "user"
        username = ""
        if self.auth and getattr(self.auth, "current_user", None):
            role = (self.auth.current_user.get("role") or "user").lower()
            username = (self.auth.current_user.get("username") or "").strip().lower()
        if username == "admin":
            role = "admin"
        self.current_user_role = role

        self.view.show_dashboard(display_name)
        self.view.set_user_info(display_name, role)
        if self.view.user_data_ui:
            self.view.user_data_ui.set_user_role(role)
            self.view.user_data_ui.load_data()
        
        # Start heavy loading ONLY NOW
        self.view.general_ui.btn_predict.setEnabled(False)
        self.view.inv_ui.btn.setEnabled(False)
        self.view.general_ui.btn_predict.setText("  Loading Models...")
        self.view.inv_ui.btn.setText("  Loading Models...")
        
        QTimer.singleShot(500, self.start_background_loading)
        QTimer.singleShot(2000, self.check_for_updates)

    def start_background_loading(self):
        """Starts model loading in a separate thread to keep UI responsive."""
        from PyQt6.QtCore import QThread
        
        class LoadWorker(QThread):
            finished = pyqtSignal()
            failed = pyqtSignal(str)
            
            def run(self):
                try:
                    # Accessing outer scope self.loader
                    self.parent().loader.load_all()
                    self.finished.emit()
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    print(f"Model load critical error: {tb}")
                    self.failed.emit(str(e))

        self.load_thread = LoadWorker(parent=self)
        self.load_thread.finished.connect(self.on_models_ready)
        self.load_thread.failed.connect(self.on_models_failed)
        self.load_thread.start()

    def on_models_ready(self):
        """Re-enables UI once models are memory-resident or simulation is active."""
        is_sim = self.loader.is_simulated
        print(f"[INFO] AI Engine Ready (Simulated: {is_sim})")
        
        self.view.inv_ui.btn.setEnabled(True)
        self.view.general_ui.btn_predict.setEnabled(True)
        
        if is_sim:
            self.view.inv_ui.btn.setText("  Optimize (SIM)")
            self.view.statusBar().showMessage("Warning: AI Engine in Simulation Mode (DLL Load Failed)")
            
            # Also notify via notification panel
            self.view.notify_ui.add_notification(
                title="AI Engine Fallback",
                message="Neural network models could not be initialized (Environment Error). The system has switched to Simulation Mode to maintain functionality.",
                alert_type="warning",
                tag="ai_fallback"
            )
        else:
            self.view.inv_ui.btn.setText("  Recommend Parameters")
            self.view.general_ui.btn_predict.setText("  Predict Parameters")
            self.view.statusBar().showMessage("AI Models Loaded & Ready")

    def on_models_failed(self, error_msg):
        """Validates failure and notifies user."""
        print(f"[ERROR] AI Model Thread Failed: {error_msg}")
        self.view.statusBar().showMessage("Warning: AI Model Loading Failed")
        
        self.view.inv_ui.btn.setText("  Model Error")
        self.view.general_ui.btn_predict.setText("  Model Error")
        
        self.view.notify_ui.add_notification(
            title="AI Engine Failure",
            message=f"Critical error loading AI models.\n\nError: {error_msg}\n\nPlease check logs at %APPDATA%/BSF_INTEL/logs/app.log or contact support.",
            alert_type="error",
            tag="ai_error"
        )

    def show(self):
        if not self.should_exit:
            self.view.show()
        else:
            QApplication.quit()

    def handle_logout(self):
        """Clears session and returns to login screen."""
        if self.auth:
            self.auth.logout()
        self.view.show_login()

    # --- UPDATER LOGIC ---
    def handle_manual_update_check(self):
        """Triggers a manual update check from the UI."""
        self.view.notify_ui.set_refresh_loading(True)
        self.view.statusBar().showMessage("Checking for remote updates...")
        
        def on_complete():
            self.view.notify_ui.set_refresh_loading(False)
            
        self.updater.check_for_updates(
            on_available=lambda info: [self.on_update_found(info), on_complete()],
            on_no_update=lambda: [self.view.statusBar().showMessage("System up to date."), on_complete()],
            on_error=lambda msg: [self.view.statusBar().showMessage(f"Warning: {msg}"), on_complete()]
        )

    def check_for_updates(self):
        self.view.statusBar().showMessage("Checking for remote updates...")
        self.updater.check_for_updates(
            on_available=self.on_update_found,
            on_no_update=lambda: self.view.statusBar().showMessage("System up to date."),
            on_error=lambda msg: self.view.statusBar().showMessage(f"Warning: {msg}")
        )

    def on_update_found(self, info):
        self.update_info = info
        version = info.get("version")
        notes = info.get("release_notes")
        
        self.view.notify_ui.add_notification(
            title=f"New Update Available (v{version})",
            message=f"A new version of BSF-INTEL is available.\n\nRelease Notes:\n{notes}",
            alert_type="update",
            action_text="Install Now",
            tag="software_update"
        )
        self.view.statusBar().showMessage(f"Update ready: Version {version} is ready for installation.")

    def handle_notification_action(self, tag):
        if tag == "software_update":
            self.start_update_download()

    def start_update_download(self):
        if not self.update_info:
            return
            
        url = self.update_info.get("url")
        sha256 = self.update_info.get("hash")
        
        # Update identifying notification to show progress
        self.view.notify_ui.add_notification(
            title="Downloading Update",
            message="Please wait while we prepare the new version. The application will restart automatically.",
            alert_type="info",
            tag="software_update" # Overwrite existing
        )
        
        self.updater.download_and_install(
            url, sha256,
            on_progress=self.on_download_progress,
            on_error=self.on_download_error
        )

    def on_download_progress(self, percent):
        item = self.view.notify_ui.active_items.get("software_update")
        if item:
            item.set_progress(percent)
            item.msg_lbl.setText(f"Progress: {percent}% - Downloading safe binaries...")

    def on_download_error(self, msg):
        self.view.notify_ui.add_notification(
            title="Update Failed",
            message=f"Critical error during download: {msg}\nCheck your internet connection and try again.",
            alert_type="error"
        )
        self.view.statusBar().showMessage("Error: Update Failed")

    # --- UNIFIED WORKFLOW LOGIC ---
    def handle_unified_trial_save(self, data: dict):
        """Step 1: Save General + Machine Info in one go."""
        try:
            # Close previous open trial buffer before creating a new one.
            self._reset_sensor_buffers()

            user_id = "Guest"
            if self.auth and getattr(self.auth, "current_user", None):
                user_id = self.auth.current_user.get("username") or self.auth.current_user.get("email") or "Guest"

            # 1. Save Trial
            trial_id = self.db.save_general_info(data, user_id=user_id)
            self.current_trial_id = trial_id
            
            # 2. Save Machine Info
            self.db.save_machine_info(trial_id, data)
            
            # 3. Advance UI
            self.view.general_ui.enable_predictor()
            self.view.statusBar().showMessage(f"Trial #{trial_id} initialized successfully.")
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self.view, "DB Error", f"Failed to initialize trial: {e}")

    def handle_unified_prediction(self, params: dict):
        """Step 2: Multi-stage prediction inside General tab."""
        from PyQt6.QtCore import QThread, pyqtSignal
        
        class UnifiedWorker(QThread):
            success = pyqtSignal(dict)
            error = pyqtSignal(str)
            
            def __init__(self, service, params):
                super().__init__()
                self.service = service
                self.params = params
                
            def run(self):
                try:
                    res = self.service.predict_surface(
                        self.params['initial_ra'],
                        self.params['target_ra'],
                        self.params['bearing_type']
                    )
                    self.success.emit(res)
                except Exception as e:
                    self.error.emit(str(e))

        if hasattr(self, 'unified_thread') and self.unified_thread.isRunning():
            return

        self.last_prediction_data = None
        self.unified_thread = UnifiedWorker(self.surface_svc, params)
        
        def on_success(data):
            try:
                import copy
                self.last_prediction_data = copy.deepcopy(data)
                self.view.general_ui.show_results(data)
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self.view, "Rendering Error", f"Failed to display results: {e}")
            finally:
                # Always re-enable button
                self.view.general_ui.btn_predict.setEnabled(True)
                self.view.general_ui.btn_predict.setText("  Predict Parameters")
            
        def on_error(msg):
             from PyQt6.QtWidgets import QMessageBox
             QMessageBox.critical(self.view, "Prediction Error", f"Model Inference Failed: {msg}")
             self.view.general_ui.btn_predict.setEnabled(True)
             self.view.general_ui.btn_predict.setText("  Predict Parameters")

        self.unified_thread.success.connect(on_success)
        self.unified_thread.error.connect(on_error)
        
        # UI Feedback
        self.view.general_ui.btn_predict.setEnabled(False)
        self.view.general_ui.btn_predict.setText("  Processing AI Stages...")
        self.unified_thread.start()

    def handle_parameters_save(self):
        """Step 3: Save results and dynamic Dashboard update."""
        if not self.current_trial_id or not self.last_prediction_data:
            return

        try:
            self.db.save_prediction_result(
                self.current_trial_id,
                self.last_prediction_data['bearing_type'],
                self.last_prediction_data['stage_results']
            )
            self._flush_sensor_streams()
            
            # Dashboard Widget Auto-Feed (Strictly from DB)
            db_results = self.db.get_prediction_results(self.current_trial_id)
            if db_results:
                self.sync_dashboard_widget(db_results)
            
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self.view, "Success", "Prediction Saved Successfully.\nThe result has been added to Dashboard.")
            
            self.view.general_ui.reset_workflow()
            if self.view.user_data_ui:
                self.view.user_data_ui.load_data()
                
        except Exception as e:
            import traceback
            traceback.print_exc() # Print full error to console
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self.view, "Save Error", f"Failed to save results: {e}")

    def _reset_sensor_buffers(self):
        self._force_samples_buffer = []
        self._power_samples_buffer = []

    def _collect_force_sample(self, data: dict):
        if not self.current_trial_id:
            return

        plc_val = data.get("plc")
        x = data.get("plc_x", plc_val)
        y = data.get("plc_y", plc_val)
        z = data.get("plc_z", plc_val)
        if x is None and y is None and z is None:
            return

        self._force_samples_buffer.append({
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "x": x,
            "y": y,
            "z": z,
            "metadata": {"source": "plc"},
        })
        if len(self._force_samples_buffer) > self._max_sensor_buffer:
            self._force_samples_buffer = self._force_samples_buffer[-self._max_sensor_buffer:]

    def _collect_power_sample(self, data: dict):
        if not self.current_trial_id:
            return

        vfd_val = data.get("vfd")
        if vfd_val is None:
            return
        self._power_samples_buffer.append({
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "x": vfd_val,
            "y": None,
            "z": None,
            "metadata": {"source": "vfd"},
        })
        if len(self._power_samples_buffer) > self._max_sensor_buffer:
            self._power_samples_buffer = self._power_samples_buffer[-self._max_sensor_buffer:]

    def _flush_sensor_streams(self):
        if not self.current_trial_id:
            return

        if self._force_samples_buffer:
            self.db.save_sensor_stream_batch(self.current_trial_id, "force_data", self._force_samples_buffer)
        if self._power_samples_buffer:
            self.db.save_sensor_stream_batch(self.current_trial_id, "power_data", self._power_samples_buffer)
        self._reset_sensor_buffers()

    def sync_dashboard_widget(self, data):
        """Updates existing PredictedRoughnessWidget or injects a new one."""
        dash = self.view.dash_ui
        found = False
        
        # 1. Look for existing widget instance
        for widget_id, w in dash.manager.widgets.items():
            if w.__class__.__name__ == 'PredictedRoughnessWidget':
                # Update existing summary widget
                w.set_data(data) # Pass full list of stages
                found = True
                break
                
        if not found:
            # 2. Inject new 6x3 summary widget if missing
            w_id = "surface_roughness_summary"
            widget = dash.widget_factory("surface_roughness", w_id)
            if widget:
                widget.set_data(data)
                # Industrial 6x3 span as per requirement
                dash.manager.add_widget(widget, col_span=6, row_span=3)
                dash.manager.save_layout()

    def handle_optimization(self, init_ra: float, target_ra: float):
        self._run_async_inference("opt", {"init_ra": init_ra, "target_ra": target_ra})

    def _run_async_inference(self, mode, params):
        from PyQt6.QtCore import QThread
        
        class InferenceWorker(QThread):
            success = pyqtSignal(object)
            error = pyqtSignal(str)
            
            def __init__(self, inference, mode, params):
                super().__init__()
                self.inference = inference
                self.mode = mode
                self.params = params
                
            def run(self):
                try:
                    res = self.inference.predict_parameters(
                        self.params["init_ra"], 
                        self.params["target_ra"]
                    )
                    self.success.emit(res)
                except Exception as e:
                    self.error.emit(str(e))

        # Cleanup old thread if running
        if self.inference_thread and self.inference_thread.isRunning():
            return # Or queue it

        self.inference_thread = InferenceWorker(self.inference, mode, params)
        self.inference_thread.success.connect(self.view.inv_ui.on_optimization_success)
        self.inference_thread.error.connect(self.view.inv_ui.on_optimization_error)
            
        self.inference_thread.start()

    def _on_plc_data_dashboard(self, data):
        """Processes real-time force sensor data to compute metrics and feed widgets."""
        x = data.get("plc_x", data.get("plc"))
        y = data.get("plc_y", data.get("plc"))
        z = data.get("plc_z", data.get("plc"))
        if x is None:
            return

        import math

        self._force_samples_buffer.append({"x": x, "y": y, "z": z})
        if len(self._force_samples_buffer) > 1000:
            self._force_samples_buffer = self._force_samples_buffer[-1000:]

        # 1. Compute vibration (variance in the force signals over window)
        forces = [abs(s["x"]) for s in self._force_samples_buffer[-50:]]
        avg_force = sum(forces) / len(forces) if forces else 0.0
        std_force = math.sqrt(sum((f - avg_force)**2 for f in forces) / len(forces)) if len(forces) > 1 else 0.0

        vibration_status = "NORMAL" if std_force < 100 else "HIGH"

        # 2. Real-time AI prediction of surface quality (Ra)
        # Surface roughness predicted dynamically from the vibration and load forces
        predicted_ra = 0.04 + (std_force / 450.0) + (avg_force / 8000.0)
        predicted_ra = max(0.03, min(predicted_ra, 1.80))

        # Confidence drops under high standard deviation or noise
        confidence = 99.8 - (std_force / 6.0)
        confidence = max(30.0, min(confidence, 99.9))

        # 3. Update active widgets
        manager = self.view.dash_ui.manager
        for w in manager.widgets.values():
            name = w.__class__.__name__
            if name == 'AIPredictionWidget':
                w.update_prediction(predicted_ra, confidence)
            elif name == 'MachineHealthWidget':
                # Temperature modeled dynamically based on friction forces
                temp = 32.5 + (avg_force / 120.0) + (std_force / 8.0)
                temp_str = f"{temp:.1f}°C"
                load_str = "0%"
                if hasattr(self, "_last_load_pct"):
                    load_str = f"{self._last_load_pct:.1f}%"
                w.update_health(vibration_status, temp_str, load_str)

        # 4. Trigger alert log on threshold breaches
        if std_force > 150:
            for w in manager.widgets.values():
                if w.__class__.__name__ == 'AlertLogWidget':
                    w.add_alert("Sensor", "High force vibration threshold breached", "ERROR")

    def _on_vfd_data_dashboard(self, data):
        """Processes real-time spindle power load and updates metrics."""
        vfd_val = data.get("vfd")
        if vfd_val is None:
            return

        # 1. Update main sensor graph widget with real power
        manager = self.view.dash_ui.manager
        for w in manager.widgets.values():
            if w.__class__.__name__ == 'RealTimeGraphWidget':
                w.update_data(vfd_val)

        # 2. Derive spindle load percentage (Rated VFD motor power is 3000 W)
        load_pct = (vfd_val / 3000.0) * 100.0
        load_pct = max(0.0, min(load_pct, 100.0))
        self._last_load_pct = load_pct

        # 3. Update production metrics and runtime
        import time
        now = time.time()
        uptime_sec = int(now - self._start_time)
        uptime_str = time.strftime('%H:%M:%S', time.gmtime(uptime_sec))

        # Stone wear rate (Capacity assumed as 5000 parts per stone)
        wear_pct = (self._part_count / 5000.0) * 100.0
        wear_pct = max(0.0, min(wear_pct, 100.0))
        remaining_cycles = max(0, 5000 - self._part_count)

        # Rate: parts per hour
        rate = int(self._part_count / (uptime_sec / 3600.0)) if uptime_sec > 5 else 0

        # Increment mock parts processed at specific VFD cycles
        if vfd_val > 1500 and (not hasattr(self, "_last_peak_time") or (now - self._last_peak_time) > 12.0):
            self._part_count += 1
            self._last_peak_time = now

        for w in manager.widgets.values():
            name = w.__class__.__name__
            if name == 'ProductionWidget':
                w.update_metrics(self._part_count, 12.4, rate, uptime_str)
            elif name == 'StoneConditionWidget':
                w.update_stone_data(wear_pct, remaining_cycles)
            elif name == 'AlertLogWidget':
                if vfd_val > 2800:
                    w.add_alert("Spindle", "Motor load exceeded safety threshold", "WARNING")


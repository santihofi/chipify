"""
settings_window.py – Modal settings dialog for persistent user preferences.

Layout is a tabbed dialog (CTkTabview): General / Simulator / Performance /
Remote.  Save / Cancel are pinned at the bottom so they remain reachable on
small displays no matter how many fields a tab grows.

The Remote tab supports multiple named profiles (e.g. lab server, cloud VM)
plus a structured preflight panel that reports the remote chipify / EDA /
PDK status. First-time host-key trust is handled by a TOFU dialog rather
than the silent AutoAddPolicy that earlier versions used.
"""
from __future__ import annotations

import os
import threading
from typing import Any

import customtkinter as ctk

from chipify import app_config, util


class SettingsWindow(ctk.CTkToplevel):
    """Modal settings dialog for persistent user preferences."""

    _ENGINE_HINTS = {
        "ngspice": "ngspice: default SPICE3 simulator",
        "vacask": "vacask: Verilog-A Circuit Analysis Kernel (PyOPUS required)",
    }
    _VALID_ENGINES = ["ngspice", "vacask"]

    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        self.title("Global Settings")
        self.geometry("680x720")
        self.minsize(640, 600)

        # grab_set needs a small delay so the window is fully mapped first
        self.after(50, self.grab_set)

        self._main_app = parent

        # ── Load + normalise config ─────────────────────────────────────────
        self._config = app_config.load_config()
        max_cores = os.cpu_count() or 1
        current_cores = int(self._config.get("num_cores") or util.get_num_cores())
        simulator_engine = self._config.get("simulator_engine", "ngspice")
        process_mode = self._config.get("process_start_method", "auto")
        chunk_size_mode = str(self._config.get("chunk_size", "auto"))
        vacask_binary = self._config.get("vacask_binary", "vacask")
        vacask_src = self._config.get("vacask_netlist_source", "xschem")
        current_theme = self._config.get("theme", "night")
        compute_target = self._config.get("compute_target", "local")

        # Remote profiles: always at least one entry, possibly auto-migrated
        # from the legacy single-host keys.
        self._profiles: list[dict[str, Any]] = [
            dict(p) for p in app_config.get_remote_profiles(self._config)
        ]
        self._active_profile_name: str = (
            self._config.get("active_remote_profile")
            or self._profiles[0]["name"]
        )
        self._profile_dirty: bool = False
        self._current_preflight_info: dict[str, Any] | None = None

        if compute_target not in ("local", "remote"):
            compute_target = "local"
        if simulator_engine not in self._VALID_ENGINES:
            simulator_engine = "ngspice"
        if process_mode not in ["auto", "forkserver", "spawn"]:
            process_mode = "auto"
        if chunk_size_mode not in ["auto", "1", "2", "4", "8", "16", "32"]:
            chunk_size_mode = "auto"
        if vacask_src not in ["xschem", "ng2vc"]:
            vacask_src = "xschem"
        if current_theme not in ["night", "dark", "light"]:
            current_theme = "night"

        # ── Layout skeleton: header / tabview / pinned buttons ──────────────
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # tabview expands

        header = ctk.CTkLabel(
            self, text="⚙️  Global Settings",
            font=ctk.CTkFont(size=17, weight="bold"),
        )
        header.grid(row=0, column=0, pady=(18, 8), sticky="n")

        self._tabs = ctk.CTkTabview(self, anchor="nw")
        self._tabs.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="nsew")
        for name in ("General", "Simulator", "Performance", "Remote"):
            self._tabs.add(name)
        tab_general = self._tabs.tab("General")
        tab_simulator = self._tabs.tab("Simulator")
        tab_perf = self._tabs.tab("Performance")
        tab_remote = self._tabs.tab("Remote")

        # Pinned button row — always visible at the bottom of the window
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, padx=24, pady=(4, 16), sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            btn_row, text="Cancel", command=self.destroy,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            btn_row, text="💾  Save", command=self._save,
            fg_color="#2ecc71", hover_color="#27ae60",
        ).grid(row=0, column=1, sticky="e")

        self._build_general_tab(
            tab_general, current_cores, max_cores, current_theme
        )
        self._build_simulator_tab(
            tab_simulator, simulator_engine, vacask_binary, vacask_src
        )
        self._build_performance_tab(
            tab_perf, process_mode, chunk_size_mode
        )
        self._build_remote_tab(tab_remote, compute_target)

    # ── General tab ─────────────────────────────────────────────────────────

    def _build_general_tab(self, parent, current_cores: int,
                           max_cores: int, current_theme: str) -> None:
        # CPU cores
        cores_outer = ctk.CTkFrame(parent, fg_color="transparent")
        cores_outer.pack(fill="x", padx=8, pady=(8, 0))

        row = ctk.CTkFrame(cores_outer, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="CPU Cores for Simulation:", anchor="w").pack(side="left")
        self._cores_lbl = ctk.CTkLabel(
            row, text=str(current_cores),
            font=ctk.CTkFont(weight="bold"), width=28,
        )
        self._cores_lbl.pack(side="right")

        self._cores_var = ctk.IntVar(value=current_cores)
        self._slider = ctk.CTkSlider(
            cores_outer,
            from_=1, to=max_cores,
            number_of_steps=max(1, max_cores - 1),
            variable=self._cores_var,
            command=self._on_cores_change,
        )
        self._slider.pack(fill="x", pady=(6, 2))
        ctk.CTkLabel(
            cores_outer,
            text=f"Range: 1 – {max_cores} logical cores",
            text_color="gray", font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

        # Appearance theme
        theme_outer = ctk.CTkFrame(parent, fg_color="transparent")
        theme_outer.pack(fill="x", padx=8, pady=(18, 8))
        ctk.CTkLabel(theme_outer, text="Appearance Theme:", anchor="w").pack(anchor="w")
        self._theme_var = ctk.StringVar(value=current_theme)
        ctk.CTkOptionMenu(
            theme_outer,
            variable=self._theme_var,
            values=["night", "dark", "light"],
            dynamic_resizing=False,
            width=180,
        ).pack(anchor="w", pady=(6, 2))
        ctk.CTkLabel(
            theme_outer,
            text="night: pitch black  •  dark: grey dark  •  light: light mode",
            text_color="gray", font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

    # ── Simulator tab ───────────────────────────────────────────────────────

    def _build_simulator_tab(self, parent, simulator_engine: str,
                             vacask_binary: str, vacask_src: str) -> None:
        self._sim_outer = ctk.CTkFrame(parent, fg_color="transparent")
        self._sim_outer.pack(fill="x", padx=8, pady=(8, 0))
        ctk.CTkLabel(self._sim_outer, text="Simulation Engine:", anchor="w").pack(anchor="w")
        self._sim_engine_var = ctk.StringVar(value=simulator_engine)
        self._sim_engine_menu = ctk.CTkOptionMenu(
            self._sim_outer,
            variable=self._sim_engine_var,
            values=self._VALID_ENGINES,
            dynamic_resizing=False,
            width=180,
            command=self._on_engine_change,
        )
        self._sim_engine_menu.pack(anchor="w", pady=(6, 2))
        self._sim_engine_hint = ctk.CTkLabel(
            self._sim_outer,
            text=self._ENGINE_HINTS.get(simulator_engine, ""),
            text_color="gray", font=ctk.CTkFont(size=11),
        )
        self._sim_engine_hint.pack(anchor="w")

        # VACASK-specific frame
        self._vacask_frame = ctk.CTkFrame(parent, fg_color="transparent")

        vc_bin_row = ctk.CTkFrame(self._vacask_frame, fg_color="transparent")
        vc_bin_row.pack(fill="x")
        ctk.CTkLabel(vc_bin_row, text="VACASK Binary:", anchor="w", width=130).pack(side="left")
        self._vacask_binary_var = ctk.StringVar(value=vacask_binary)
        ctk.CTkEntry(
            vc_bin_row, textvariable=self._vacask_binary_var,
            placeholder_text="vacask", width=200,
        ).pack(side="left", padx=(8, 0))

        vc_src_row = ctk.CTkFrame(self._vacask_frame, fg_color="transparent")
        vc_src_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(vc_src_row, text="Netlist Source:", anchor="w", width=130).pack(side="left")
        self._vacask_src_var = ctk.StringVar(value=vacask_src)
        ctk.CTkOptionMenu(
            vc_src_row,
            variable=self._vacask_src_var,
            values=["xschem", "ng2vc"],
            dynamic_resizing=False,
            width=200,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            self._vacask_frame,
            text="Requires PyOPUS  (pip install chipify[vacask])  and vacask on PATH",
            text_color="gray", font=ctk.CTkFont(size=11), wraplength=440,
        ).pack(anchor="w", pady=(6, 0))

        if simulator_engine == "vacask":
            self._vacask_frame.pack(fill="x", padx=8, pady=(12, 8),
                                    after=self._sim_outer)

    # ── Performance tab ─────────────────────────────────────────────────────

    def _build_performance_tab(self, parent, process_mode: str,
                               chunk_size_mode: str) -> None:
        # Process start method
        proc_outer = ctk.CTkFrame(parent, fg_color="transparent")
        proc_outer.pack(fill="x", padx=8, pady=(8, 0))
        ctk.CTkLabel(proc_outer, text="Multiprocessing Start Method:", anchor="w").pack(anchor="w")
        self._proc_mode_var = ctk.StringVar(value=process_mode)
        ctk.CTkOptionMenu(
            proc_outer,
            variable=self._proc_mode_var,
            values=["auto", "forkserver", "spawn"],
            dynamic_resizing=False,
            width=180,
        ).pack(anchor="w", pady=(6, 2))
        ctk.CTkLabel(
            proc_outer,
            text="auto = forkserver on Linux, spawn elsewhere",
            text_color="gray", font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

        # Chunk size
        chunk_outer = ctk.CTkFrame(parent, fg_color="transparent")
        chunk_outer.pack(fill="x", padx=8, pady=(18, 0))
        ctk.CTkLabel(chunk_outer, text="Batch Chunk Size:", anchor="w").pack(anchor="w")
        self._chunk_var = ctk.StringVar(value=chunk_size_mode)
        ctk.CTkOptionMenu(
            chunk_outer,
            variable=self._chunk_var,
            values=["auto", "1", "2", "4", "8", "16", "32", "64", "128", "256"],
            dynamic_resizing=False,
            width=180,
        ).pack(anchor="w", pady=(6, 2))
        ctk.CTkLabel(
            chunk_outer,
            text="Higher values can improve throughput, lower values improve responsiveness",
            text_color="gray", font=ctk.CTkFont(size=11), wraplength=440,
        ).pack(anchor="w")

        # Live plotting
        live_outer = ctk.CTkFrame(parent, fg_color="transparent")
        live_outer.pack(fill="x", padx=8, pady=(18, 8))
        ctk.CTkLabel(
            live_outer,
            text="Live plotting during simulation",
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w")

        self._live_plot_var = ctk.BooleanVar(value=app_config.is_live_plotting_enabled())
        ctk.CTkCheckBox(
            live_outer,
            text="Enable live plotting during simulation",
            variable=self._live_plot_var,
            command=self._on_live_plot_toggle,
        ).pack(anchor="w", pady=(8, 4))

        throttle_row = ctk.CTkFrame(live_outer, fg_color="transparent")
        throttle_row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(throttle_row, text="Plot refresh interval (ms):").pack(side="left", padx=(0, 8))
        self._throttle_var = ctk.StringVar(value=str(app_config.get_live_throttle_ms()))
        throttle_entry = ctk.CTkEntry(throttle_row, textvariable=self._throttle_var, width=72)
        throttle_entry.pack(side="left")
        throttle_entry.bind("<FocusOut>", self._on_throttle_change_evt)
        throttle_entry.bind("<Return>", self._on_throttle_change_evt)
        ctk.CTkLabel(
            live_outer,
            text="500–5000 ms (lower = more frequent redraws)",
            text_color="gray",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(4, 0))

    # ── Remote tab ──────────────────────────────────────────────────────────

    def _build_remote_tab(self, parent, compute_target: str) -> None:
        self._compute_outer = ctk.CTkFrame(parent, fg_color="transparent")
        self._compute_outer.pack(fill="x", padx=8, pady=(8, 0))
        ctk.CTkLabel(
            self._compute_outer, text="Compute Target:", anchor="w"
        ).pack(anchor="w")
        self._compute_target_var = ctk.StringVar(value=compute_target)
        ctk.CTkOptionMenu(
            self._compute_outer,
            variable=self._compute_target_var,
            values=["local", "remote"],
            dynamic_resizing=False,
            width=180,
            command=self._on_compute_target_change,
        ).pack(anchor="w", pady=(6, 2))
        ctk.CTkLabel(
            self._compute_outer,
            text="local: multiprocessing pool  •  remote: offload via SSH",
            text_color="gray", font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

        # Scrollable host so the profile editor can grow.
        self._remote_frame = ctk.CTkScrollableFrame(
            parent, fg_color="transparent", label_text="",
            height=440,
        )

        # ── Profile selector row ───────────────────────────────────────
        prof_row = ctk.CTkFrame(self._remote_frame, fg_color="transparent")
        prof_row.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(
            prof_row, text="Profile:", anchor="w", width=130,
        ).pack(side="left")
        self._profile_var = ctk.StringVar(value=self._active_profile_name)
        self._profile_menu = ctk.CTkOptionMenu(
            prof_row,
            variable=self._profile_var,
            values=[p["name"] for p in self._profiles],
            dynamic_resizing=False,
            width=200,
            command=self._on_profile_select,
        )
        self._profile_menu.pack(side="left", padx=(8, 6))
        ctk.CTkButton(
            prof_row, text="+ Add", width=60,
            command=self._on_profile_add,
        ).pack(side="left", padx=(2, 4))
        ctk.CTkButton(
            prof_row, text="Rename…", width=80,
            command=self._on_profile_rename,
        ).pack(side="left", padx=(2, 4))
        self._profile_del_btn = ctk.CTkButton(
            prof_row, text="Delete", width=70,
            fg_color="#a93226", hover_color="#7b241c",
            command=self._on_profile_delete,
        )
        self._profile_del_btn.pack(side="left", padx=(2, 4))

        # ── Editable profile fields ────────────────────────────────────
        self._build_profile_fields(self._remote_frame)

        # ── Preflight panel ────────────────────────────────────────────
        action_row = ctk.CTkFrame(self._remote_frame, fg_color="transparent")
        action_row.pack(fill="x", pady=(12, 4))
        self._remote_test_btn = ctk.CTkButton(
            action_row, text="🔌  Test Connection", width=180,
            command=self._on_test_connection,
        )
        self._remote_test_btn.pack(side="left")
        self._remote_busy_lbl = ctk.CTkLabel(
            action_row, text="", text_color="orange",
            font=ctk.CTkFont(size=11),
        )
        self._remote_busy_lbl.pack(side="left", padx=(10, 0))

        self._preflight_box = ctk.CTkTextbox(
            self._remote_frame, height=180, wrap="none",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self._preflight_box.pack(fill="both", expand=False, pady=(6, 6))
        self._preflight_box.insert("end", "(no preflight result yet)")
        self._preflight_box.configure(state="disabled")

        ctk.CTkLabel(
            self._remote_frame,
            text=(
                "Auth: SSH key (no passwords stored). On first connection the\n"
                "host fingerprint is shown for you to trust.\n\n"
                "Server side, inside the iic-osic-tools container:\n"
                "    pip install --user 'chipify[remote]'\n"
                "    chipify-cli install-server"
            ),
            text_color="gray", font=ctk.CTkFont(size=11), wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(4, 4))

        # Load fields from the currently-active profile.
        self._load_profile_into_fields(self._active_profile_name)
        self._update_profile_delete_state()

        if compute_target == "remote":
            self._remote_frame.pack(
                fill="both", expand=True, padx=8, pady=(12, 8),
                after=self._compute_outer,
            )

    def _build_profile_fields(self, parent) -> None:
        """Create the entry widgets that bind to the currently-selected profile."""
        def _row(parent_, label_text: str, width_label: int = 130):
            r = ctk.CTkFrame(parent_, fg_color="transparent")
            r.pack(fill="x", pady=(4, 0))
            ctk.CTkLabel(
                r, text=label_text, anchor="w", width=width_label
            ).pack(side="left")
            return r

        host_row = _row(parent, "Server IP / Host:")
        self._remote_host_var = ctk.StringVar()
        ctk.CTkEntry(
            host_row, textvariable=self._remote_host_var,
            placeholder_text="e.g. 10.0.0.5 or sim.example.com", width=320,
        ).pack(side="left", padx=(8, 0))

        port_row = _row(parent, "Port:")
        self._remote_port_var = ctk.StringVar()
        ctk.CTkEntry(
            port_row, textvariable=self._remote_port_var,
            placeholder_text="22", width=80,
        ).pack(side="left", padx=(8, 0))

        user_row = _row(parent, "Username:")
        self._remote_user_var = ctk.StringVar()
        ctk.CTkEntry(
            user_row, textvariable=self._remote_user_var,
            placeholder_text="designer / headless / ubuntu", width=320,
        ).pack(side="left", padx=(8, 0))

        key_row = _row(parent, "SSH Key Path:")
        self._remote_key_var = ctk.StringVar()
        ctk.CTkEntry(
            key_row, textvariable=self._remote_key_var,
            placeholder_text="~/.ssh/id_ed25519 (blank = use ssh-agent)", width=240,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            key_row, text="Browse…", width=70,
            command=self._on_browse_key,
        ).pack(side="left", padx=(6, 0))

        agent_row = _row(parent, "")
        self._use_agent_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            agent_row,
            text="Also try ssh-agent / ~/.ssh defaults if key auth fails",
            variable=self._use_agent_var,
        ).pack(side="left", padx=(8, 0))

        alias_row = _row(parent, "SSH-config alias:")
        self._ssh_config_alias_var = ctk.StringVar()
        ctk.CTkEntry(
            alias_row, textvariable=self._ssh_config_alias_var,
            placeholder_text="(optional) name from ~/.ssh/config — enables ProxyJump",
            width=320,
        ).pack(side="left", padx=(8, 0))

        wd_row = _row(parent, "Remote Work Dir:")
        self._remote_workdir_var = ctk.StringVar()
        ctk.CTkEntry(
            wd_row, textvariable=self._remote_workdir_var,
            placeholder_text="/tmp/chipify_remote", width=320,
        ).pack(side="left", padx=(8, 0))

        cmd_row = _row(parent, "Remote Command:")
        self._remote_cmd_var = ctk.StringVar()
        ctk.CTkEntry(
            cmd_row, textvariable=self._remote_cmd_var,
            placeholder_text="(blank = auto-detect /usr/local/bin/chipify-remote, ~/.local/bin/chipify-remote, …)",
            width=320,
        ).pack(side="left", padx=(8, 0))

        env_row = _row(parent, "Env file (remote):")
        self._remote_env_var = ctk.StringVar()
        ctk.CTkEntry(
            env_row, textvariable=self._remote_env_var,
            placeholder_text="(optional) e.g. ~/.chipify-remote.env",
            width=320,
        ).pack(side="left", padx=(8, 0))

        flags_row = _row(parent, "")
        self._keep_on_fail_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            flags_row,
            text="Keep remote run dir on failure (for ssh-in debugging)",
            variable=self._keep_on_fail_var,
        ).pack(side="left", padx=(8, 0))

    # ── Callbacks ───────────────────────────────────────────────────────────

    def _on_cores_change(self, value: float) -> None:
        self._cores_lbl.configure(text=str(int(value)))

    def _on_live_plot_toggle(self) -> None:
        app_config.save_config_key("live_plotting_enabled", bool(self._live_plot_var.get()))

    def _on_throttle_change_evt(self, _evt=None) -> None:
        try:
            ms = max(500, min(5000, int(self._throttle_var.get())))
        except (ValueError, TypeError):
            ms = 1500
        self._throttle_var.set(str(ms))
        app_config.save_config_key("live_plot_throttle_ms", ms)
        main = self._main_app
        for t in getattr(main, "_all_throttles", []) or []:
            try:
                t.update_interval(ms)
            except Exception:
                pass
        mp = getattr(main, "multiplot_window", None)
        if mp is not None and hasattr(mp, "_live_throttle"):
            try:
                mp._live_throttle.update_interval(ms)
            except Exception:
                pass

    def _on_engine_change(self, choice: str) -> None:
        self._sim_engine_hint.configure(text=self._ENGINE_HINTS.get(choice, ""))
        if choice == "vacask":
            self._vacask_frame.pack(fill="x", padx=8, pady=(12, 8),
                                    after=self._sim_outer)
        else:
            self._vacask_frame.pack_forget()

    def _on_compute_target_change(self, choice: str) -> None:
        if choice == "remote":
            self._remote_frame.pack(
                fill="both", expand=True, padx=8, pady=(12, 8),
                after=self._compute_outer,
            )
        else:
            self._remote_frame.pack_forget()

    def _on_browse_key(self) -> None:
        from tkinter import filedialog
        initial = self._remote_key_var.get() or os.path.expanduser("~/.ssh")
        if not os.path.isdir(initial):
            initial = os.path.dirname(initial) or os.path.expanduser("~")
        path = filedialog.askopenfilename(
            parent=self,
            title="Select SSH private key",
            initialdir=initial,
        )
        if path:
            self._remote_key_var.set(path)

    # ── Profile editing helpers ─────────────────────────────────────────

    def _current_profile_dict(self) -> dict[str, Any]:
        """Snapshot the entry fields into a profile dict."""
        try:
            port = int(self._remote_port_var.get().strip() or "22")
        except (TypeError, ValueError):
            port = 22
        return {
            "name": self._active_profile_name,
            "host": self._remote_host_var.get().strip(),
            "port": port,
            "user": self._remote_user_var.get().strip(),
            "key_path": self._remote_key_var.get().strip(),
            "work_dir": (self._remote_workdir_var.get().strip()
                         or "/tmp/chipify_remote"),
            "wrapper": self._remote_cmd_var.get().strip(),
            "ssh_config_alias": self._ssh_config_alias_var.get().strip(),
            "use_agent": bool(self._use_agent_var.get()),
            "keep_on_failure": bool(self._keep_on_fail_var.get()),
            "env_file": self._remote_env_var.get().strip(),
        }

    def _commit_current_profile(self) -> None:
        """Write the current fields back into ``self._profiles`` in place."""
        snapshot = self._current_profile_dict()
        for i, p in enumerate(self._profiles):
            if p["name"] == self._active_profile_name:
                self._profiles[i] = snapshot
                return
        self._profiles.append(snapshot)

    def _load_profile_into_fields(self, name: str) -> None:
        for p in self._profiles:
            if p["name"] == name:
                break
        else:
            return
        self._remote_host_var.set(p.get("host", "") or "")
        self._remote_port_var.set(str(p.get("port", 22) or 22))
        self._remote_user_var.set(p.get("user", "") or "")
        self._remote_key_var.set(p.get("key_path", "") or "")
        self._remote_workdir_var.set(
            p.get("work_dir", "/tmp/chipify_remote") or "/tmp/chipify_remote"
        )
        self._remote_cmd_var.set(p.get("wrapper", "") or "")
        self._ssh_config_alias_var.set(p.get("ssh_config_alias", "") or "")
        self._remote_env_var.set(p.get("env_file", "") or "")
        self._use_agent_var.set(bool(p.get("use_agent", True)))
        self._keep_on_fail_var.set(bool(p.get("keep_on_failure", False)))
        self._active_profile_name = name
        self._set_preflight_message("(no preflight result yet)", color=None)

    def _refresh_profile_menu(self, select: str | None = None) -> None:
        names = [p["name"] for p in self._profiles] or ["default"]
        self._profile_menu.configure(values=names)
        if select and select in names:
            self._profile_var.set(select)
        elif self._profile_var.get() not in names:
            self._profile_var.set(names[0])
        self._update_profile_delete_state()

    def _update_profile_delete_state(self) -> None:
        self._profile_del_btn.configure(
            state="disabled" if len(self._profiles) <= 1 else "normal"
        )

    def _on_profile_select(self, choice: str) -> None:
        if choice == self._active_profile_name:
            return
        self._commit_current_profile()
        self._load_profile_into_fields(choice)

    def _on_profile_add(self) -> None:
        self._commit_current_profile()
        existing = {p["name"] for p in self._profiles}
        base = "profile"
        i = 1
        while f"{base}_{i}" in existing:
            i += 1
        new_name = f"{base}_{i}"
        new = dict(app_config.DEFAULT_REMOTE_PROFILE)
        new["name"] = new_name
        self._profiles.append(new)
        self._refresh_profile_menu(select=new_name)
        self._load_profile_into_fields(new_name)

    def _on_profile_rename(self) -> None:
        dialog = ctk.CTkInputDialog(
            text=f"New name for profile '{self._active_profile_name}':",
            title="Rename profile",
        )
        new_name = (dialog.get_input() or "").strip()
        if not new_name or new_name == self._active_profile_name:
            return
        if any(p["name"] == new_name for p in self._profiles):
            self._set_preflight_message(
                f"A profile named '{new_name}' already exists.",
                color="#e74c3c",
            )
            return
        for p in self._profiles:
            if p["name"] == self._active_profile_name:
                p["name"] = new_name
                break
        self._active_profile_name = new_name
        self._refresh_profile_menu(select=new_name)

    def _on_profile_delete(self) -> None:
        if len(self._profiles) <= 1:
            return
        target = self._active_profile_name
        self._profiles = [
            p for p in self._profiles if p["name"] != target
        ]
        new_active = self._profiles[0]["name"]
        self._refresh_profile_menu(select=new_active)
        self._load_profile_into_fields(new_active)

    # ── Preflight + TOFU ────────────────────────────────────────────────

    def _set_preflight_message(self, msg: str, color: str | None = None) -> None:
        self._preflight_box.configure(state="normal")
        self._preflight_box.delete("1.0", "end")
        self._preflight_box.insert("end", msg)
        self._preflight_box.configure(state="disabled")
        if color:
            self._remote_busy_lbl.configure(text="", text_color=color)

    def _on_test_connection(self) -> None:
        # Commit current entry fields into the active profile so the worker
        # operates on the same dict the user is staring at.
        self._commit_current_profile()
        profile_dict = self._current_profile_dict()

        self._remote_test_btn.configure(state="disabled")
        self._remote_busy_lbl.configure(
            text="Connecting…", text_color="orange",
        )
        self._set_preflight_message("Running preflight on remote…")

        def _worker() -> None:
            try:
                from chipify.remote_dispatcher import (
                    RemoteProfile, test_connection,
                )
            except ImportError as exc:
                self.after(0, self._set_preflight_result,
                           False, f"paramiko missing: {exc}", {})
                return
            profile = RemoteProfile.from_dict(profile_dict)
            ok, msg, info = test_connection(profile=profile)
            self.after(0, self._set_preflight_result, ok, msg, info)

        threading.Thread(target=_worker, daemon=True).start()

    def _set_preflight_result(
        self, ok: bool, msg: str, info: dict[str, Any]
    ) -> None:
        self._remote_test_btn.configure(state="normal")
        self._current_preflight_info = info or {}
        if not ok and info and info.get("needs_trust"):
            self._remote_busy_lbl.configure(
                text="Host key needs to be trusted.",
                text_color="orange",
            )
            self._set_preflight_message(msg)
            self._show_trust_dialog(info)
            return
        if ok:
            self._remote_busy_lbl.configure(
                text="OK", text_color="#2ecc71",
            )
        else:
            self._remote_busy_lbl.configure(
                text="Failed", text_color="#e74c3c",
            )
        self._set_preflight_message(msg)

    def _show_trust_dialog(self, info: dict[str, Any]) -> None:
        host = info.get("host", "")
        port = int(info.get("port") or 22)
        fp = info.get("fingerprint_sha256", "")
        key_type = info.get("key_type", "ssh-key")

        dlg = ctk.CTkToplevel(self)
        dlg.title("Trust remote host?")
        dlg.geometry("520x260")
        dlg.transient(self)
        dlg.after(50, dlg.grab_set)

        ctk.CTkLabel(
            dlg,
            text=f"Unknown host: {host}:{port}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(18, 4))
        ctk.CTkLabel(
            dlg,
            text=f"{key_type} fingerprint",
            text_color="gray",
            font=ctk.CTkFont(size=11),
        ).pack()
        ctk.CTkLabel(
            dlg,
            text=f"SHA256:{fp}",
            font=ctk.CTkFont(family="Consolas", size=12),
        ).pack(pady=(2, 14))
        ctk.CTkLabel(
            dlg,
            text=(
                "If this matches the value printed by `ssh-keygen -lf` on the\n"
                "server, click Trust. Otherwise abort and verify out-of-band."
            ),
            text_color="gray",
            font=ctk.CTkFont(size=11),
            justify="center",
        ).pack(pady=(0, 12))

        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(pady=(6, 12))

        def _trust() -> None:
            dlg.destroy()
            self._do_trust_then_retest(info)

        def _abort() -> None:
            dlg.destroy()
            self._remote_busy_lbl.configure(
                text="Host not trusted; connection canceled.",
                text_color="#e74c3c",
            )

        ctk.CTkButton(
            btns, text="Abort", fg_color="transparent", border_width=1,
            command=_abort,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            btns, text="Trust this fingerprint",
            fg_color="#2ecc71", hover_color="#27ae60",
            command=_trust,
        ).pack(side="left", padx=8)

    def _do_trust_then_retest(self, info: dict[str, Any]) -> None:
        self._remote_test_btn.configure(state="disabled")
        self._remote_busy_lbl.configure(
            text="Persisting host key…", text_color="orange",
        )

        profile_dict = self._current_profile_dict()
        host = info.get("host", "") or profile_dict.get("host", "")
        port = int(info.get("port") or profile_dict.get("port", 22))
        fp = info.get("fingerprint_sha256", "")
        key_type = info.get("key_type", "")

        def _worker() -> None:
            from chipify.remote_dispatcher import (
                RemoteProfile, test_connection, trust_host_fingerprint,
            )
            try:
                trust_host_fingerprint(
                    host=host, port=port, key_type=key_type,
                    fingerprint_sha256=fp,
                    username=profile_dict.get("user", ""),
                    key_path=profile_dict.get("key_path", ""),
                )
            except Exception:
                pass
            profile = RemoteProfile.from_dict(profile_dict)
            ok, msg, info2 = test_connection(
                profile=profile, trust_new_hostkey=True,
            )
            self.after(0, self._set_preflight_result, ok, msg, info2)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Save ────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        self._config["num_cores"] = int(self._cores_var.get())
        self._config["simulator_engine"] = self._sim_engine_var.get()
        self._config["vacask_binary"] = self._vacask_binary_var.get().strip() or "vacask"
        self._config["vacask_netlist_source"] = self._vacask_src_var.get()
        self._config["process_start_method"] = self._proc_mode_var.get()
        self._config["chunk_size"] = self._chunk_var.get()
        self._config["live_plotting_enabled"] = bool(self._live_plot_var.get())
        try:
            self._config["live_plot_throttle_ms"] = max(
                500, min(5000, int(self._throttle_var.get()))
            )
        except (ValueError, TypeError):
            self._config["live_plot_throttle_ms"] = 1500
        new_theme = self._theme_var.get()
        self._config["theme"] = new_theme

        # Compute target + named profiles. The single-host legacy fields
        # are mirrored from the active profile inside save_remote_profiles().
        self._config["compute_target"] = self._compute_target_var.get()
        self._commit_current_profile()

        app_config.save_config(self._config)
        app_config.save_remote_profiles(
            self._profiles, active_name=self._active_profile_name,
        )

        if hasattr(self._main_app, "change_theme"):
            self._main_app.change_theme(new_theme)
        self.destroy()

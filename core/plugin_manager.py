# -*- coding: utf-8 -*-
"""
游戏插件管理与分区扫描器
负责动态检测 games/ 目录下的所有游戏分区，读取 manifest.json 元数据
"""
import importlib.util
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

GAMES_DIR = Path(__file__).parent.parent / "games"


class GamePlugin:
    def __init__(self, folder_path: Path, manifest: dict, config: dict):
        self.folder_path = folder_path
        self.id: str = manifest.get("id", folder_path.name)
        self.name: str = manifest.get("name", folder_path.name)
        self.icon: str = manifest.get("icon", "GAME")
        self.env: str = manifest.get("env", "PC 本地")
        self.description: str = manifest.get("description", "")
        self.tasks: List[dict] = manifest.get("tasks", [])
        self.sections: List[dict] = manifest.get("sections", [])
        self.config: dict = config

    def save_config(self):
        config_path = self.folder_path / "config.json"
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[错误] 保存游戏 {self.name} 配置失败: {e}")

    def save_manifest(self):
        manifest_path = self.folder_path / "manifest.json"
        try:
            manifest_data = {
                "id": self.id,
                "name": self.name,
                "icon": self.icon,
                "env": self.env,
                "description": self.description,
            }
            if self.sections:
                manifest_data["sections"] = self.sections
            manifest_data["tasks"] = self.tasks
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[错误] 保存游戏 {self.name} 元数据失败: {e}")

    def get_runner_module(self):
        """动态加载该游戏分区下的 runner.py"""
        runner_path = self.folder_path / "runner.py"
        if not runner_path.is_file():
            return None
        spec = importlib.util.spec_from_file_location(f"games.{self.id}.runner", runner_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        return None


class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, GamePlugin] = {}
        self.scan_plugins()

    def scan_plugins(self) -> Dict[str, GamePlugin]:
        """扫描 games/ 目录下包含 manifest.json 的所有游戏子目录"""
        self.plugins.clear()
        if not GAMES_DIR.exists():
            GAMES_DIR.mkdir(parents=True, exist_ok=True)

        for folder in GAMES_DIR.iterdir():
            if folder.is_dir() and not folder.name.startswith(("_", ".")):
                manifest_file = folder / "manifest.json"
                if manifest_file.is_file():
                    try:
                        with open(manifest_file, "r", encoding="utf-8-sig") as f:
                            manifest = json.load(f)
                        
                        config_file = folder / "config.json"
                        config = {}
                        if config_file.is_file():
                            with open(config_file, "r", encoding="utf-8-sig") as f:
                                config = json.load(f)

                        plugin = GamePlugin(folder, manifest, config)
                        self.plugins[plugin.id] = plugin
                    except Exception as e:
                        print(f"[警告] 加载游戏分区 {folder.name} 失败: {e}")

        return self.plugins

    def get_plugin(self, game_id: str) -> Optional[GamePlugin]:
        return self.plugins.get(game_id)

    def get_all_plugins(self) -> List[GamePlugin]:
        return list(self.plugins.values())


# 全局单例管理器
plugin_manager = PluginManager()

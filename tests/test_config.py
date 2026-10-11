# -*- coding: utf-8 -*-
"""config 模块单元测试：配置合并优先级。"""

import json

import pytest

from codementor.config import Config


class TestLoad:
    def test_defaults_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # 避免读到当前目录的 config.json
        # 开发机上项目根目录可能存在真实 config.json，一并隔离
        monkeypatch.setattr("codementor.config.PROJECT_ROOT", tmp_path)
        for var in ("CODEMENTOR_API_KEY", "CODEMENTOR_BASE_URL", "CODEMENTOR_MODEL"):
            monkeypatch.delenv(var, raising=False)
        cfg = Config.load()
        assert cfg.api_key == ""
        assert cfg.max_iterations == 8
        assert cfg.request_timeout == 180
        assert cfg.base_url == "https://api.openai.com/v1"

    def test_config_file_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("codementor.config.PROJECT_ROOT", tmp_path)  # 隔离真实 .env
        for var in ("CODEMENTOR_API_KEY", "CODEMENTOR_MODEL"):
            monkeypatch.delenv(var, raising=False)
        conf = tmp_path / "config.json"
        conf.write_text(json.dumps({"model": "qwen-plus", "max_iterations": 5}), encoding="utf-8")
        cfg = Config.load()
        assert cfg.model == "qwen-plus"
        assert cfg.max_iterations == 5

    def test_env_overrides_config_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        conf = tmp_path / "config.json"
        conf.write_text(json.dumps({"model": "from-file"}), encoding="utf-8")
        monkeypatch.setenv("CODEMENTOR_MODEL", "from-env")
        monkeypatch.setenv("CODEMENTOR_API_KEY", "sk-env")
        cfg = Config.load()
        assert cfg.model == "from-env"
        assert cfg.api_key == "sk-env"

    def test_broken_config_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.json").write_text("{ not json", encoding="utf-8")
        with pytest.raises(ValueError, match="解析失败"):
            Config.load()

    def test_base_url_trailing_slash_stripped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("codementor.config.PROJECT_ROOT", tmp_path)  # 隔离真实 .env
        conf = tmp_path / "config.json"
        conf.write_text(json.dumps({"base_url": "http://x/v1/"}), encoding="utf-8")
        assert Config.load().base_url == "http://x/v1"


class TestEnvFile:
    def test_env_file_loaded_and_real_env_wins(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("codementor.config.PROJECT_ROOT", tmp_path)
        (tmp_path / ".env").write_text(
            '# 注释\nCODEMENTOR_MODEL=from-dotenv\n'
            'CODEMENTOR_API_KEY="sk-dot-env"\nexport CODEMENTOR_BASE_URL=http://dot\n',
            encoding="utf-8",
        )
        monkeypatch.delenv("CODEMENTOR_MODEL", raising=False)
        cfg = Config.load()
        assert cfg.model == "from-dotenv"
        assert cfg.api_key == "sk-dot-env"      # 引号被剥掉
        assert cfg.base_url == "http://dot"     # export 前缀被剥掉

        monkeypatch.setenv("CODEMENTOR_MODEL", "from-env")   # 真实环境变量 > .env
        assert Config.load().model == "from-env"

    def test_env_file_beats_config_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("codementor.config.PROJECT_ROOT", tmp_path)
        (tmp_path / ".env").write_text("CODEMENTOR_MODEL=from-dotenv\n", encoding="utf-8")
        (tmp_path / "config.json").write_text(json.dumps({"model": "from-json"}), encoding="utf-8")
        monkeypatch.delenv("CODEMENTOR_MODEL", raising=False)
        assert Config.load().model == "from-dotenv"


class TestWriteEnvFile:
    def test_creates_new_file(self, tmp_path):
        from codementor.config import write_env_file
        path = write_env_file(
            {"CODEMENTOR_API_KEY": "sk-1", "CODEMENTOR_MODEL": "m1"},
            path=tmp_path / ".env",
        )
        text = path.read_text(encoding="utf-8")
        assert "CODEMENTOR_API_KEY=sk-1" in text
        assert "CODEMENTOR_MODEL=m1" in text
        assert "配置向导" in text

    def test_updates_existing_keys_preserves_rest(self, tmp_path):
        from codementor.config import write_env_file
        env = tmp_path / ".env"
        env.write_text(
            "# 我的注释\nCODEMENTOR_MODEL=old-model\nOTHER_TOOL=keep-me\n",
            encoding="utf-8",
        )
        write_env_file(
            {"CODEMENTOR_MODEL": "new-model", "CODEMENTOR_API_KEY": "sk-2"},
            path=env,
        )
        text = env.read_text(encoding="utf-8")
        assert "CODEMENTOR_MODEL=new-model" in text
        assert "old-model" not in text
        assert "# 我的注释" in text        # 注释保留
        assert "OTHER_TOOL=keep-me" in text  # 无关键保留
        assert "CODEMENTOR_API_KEY=sk-2" in text  # 新键追加

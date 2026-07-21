import app_config


def test_load_config_returns_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "get_config_dir", lambda: str(tmp_path))
    cfg = app_config.load_config()
    assert cfg["theme"] == "flatly"
    assert cfg["recent_files"] == []


def test_save_and_load_config_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "get_config_dir", lambda: str(tmp_path))
    cfg = app_config.load_config()
    cfg["theme"] = "darkly"
    app_config.save_config(cfg)
    reloaded = app_config.load_config()
    assert reloaded["theme"] == "darkly"


def test_add_recent_file_dedupes_and_caps(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "get_config_dir", lambda: str(tmp_path))
    cfg = app_config.load_config()
    for i in range(app_config.MAX_RECENT + 5):
        app_config.add_recent_file(cfg, f"file{i}.csv")
    assert len(cfg["recent_files"]) == app_config.MAX_RECENT
    assert cfg["recent_files"][0] == f"file{app_config.MAX_RECENT + 4}.csv"

    app_config.add_recent_file(cfg, "file0.csv")
    # re-adding an existing (now-evicted) path just moves it back to the front, no duplicates
    assert cfg["recent_files"].count("file0.csv") == 1
    assert cfg["recent_files"][0] == "file0.csv"

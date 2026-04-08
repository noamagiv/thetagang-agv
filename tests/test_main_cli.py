from click.testing import CliRunner

from thetagang.main import cli


def test_cli_passes_basic_flags(monkeypatch, tmp_path):
    config_path = tmp_path / "thetagang.toml"
    config_path.write_text("x=1\n", encoding="utf8")

    captured = {}

    def fake_start(config, without_ibc, dry_run):
        captured["config"] = config
        captured["without_ibc"] = without_ibc
        captured["dry_run"] = dry_run

    monkeypatch.setattr("thetagang.thetagang.start", fake_start)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--config", str(config_path), "--dry-run", "--without-ibc"],
    )

    assert result.exit_code == 0
    assert captured["config"] == str(config_path)
    assert captured["without_ibc"] is True
    assert captured["dry_run"] is True


def test_cli_dry_run_defaults_to_false(monkeypatch, tmp_path):
    config_path = tmp_path / "thetagang.toml"
    config_path.write_text("x=1\n", encoding="utf8")

    captured = {}

    def fake_start(config, without_ibc, dry_run):
        captured["dry_run"] = dry_run
        captured["without_ibc"] = without_ibc

    monkeypatch.setattr("thetagang.thetagang.start", fake_start)

    CliRunner().invoke(cli, ["--config", str(config_path)])

    assert captured["dry_run"] is False
    assert captured["without_ibc"] is False

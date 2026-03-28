def test_cli_setters_runs(capsys):
    from dotday import main

    # Should run without raising and print available plugins
    main(["setters"])
    captured = capsys.readouterr()
    assert "no setter plugins found" not in captured.out.lower()


def test_cli_output_flag_creates_file(tmp_path):
    from dotday import main

    out = tmp_path / "wallpaper.png"
    # Run the CLI 'run' command with -o to override output path
    main(["run", "-o", str(out)])
    assert out.exists()
    assert out.stat().st_size > 0

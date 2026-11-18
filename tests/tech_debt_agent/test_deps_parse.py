from backend.agents.tech_debt_agent.scanners import deps


def _pkg(current, fixes_per_vuln, name="requests", range_type="ECOSYSTEM"):
    return {
        "package": {"name": name, "version": current},
        "vulnerabilities": [
            {
                "id": f"V{i}",
                "affected": [
                    {
                        "package": {"name": name},
                        "ranges": [
                            {
                                "type": range_type,
                                "events": [{"introduced": "0"}] + [{"fixed": x} for x in fx],
                            }
                        ],
                    }
                ],
            }
            for i, fx in enumerate(fixes_per_vuln)
        ],
    }


def test_min_fixed_cubre_todas_las_vulnerabilidades():
    assert deps.min_fixed_version(_pkg("2.19.0", [["2.20.0"], ["2.31.0", "3.0.0"]])) == "2.31.0"


def test_min_fixed_ignora_fixed_anteriores_a_la_actual():
    assert deps.min_fixed_version(_pkg("2.25.0", [["2.20.0", "2.26.1"]])) == "2.26.1"


def test_sin_fixed_devuelve_none():
    assert deps.min_fixed_version(_pkg("1.0", [[]])) is None


def test_rangos_git_se_ignoran():
    # Salida real de osv (idna): un rango GIT con un hash de commit como "fixed".
    pkg = _pkg("2.7.0", [["3.7"]], name="idna")
    pkg["vulnerabilities"][0]["affected"][0]["ranges"].insert(
        0,
        {"type": "GIT", "events": [{"introduced": "0"}, {"fixed": "1d365e17e10d72d0b78763"}]},
    )
    assert deps.min_fixed_version(pkg) == "3.7"


def test_solo_rango_git_devuelve_none():
    assert deps.min_fixed_version(_pkg("2.7.0", [["1d365e17e1"]], range_type="GIT")) is None


def test_afectado_de_otro_paquete_no_cuenta():
    # Salida real de osv (lodash): el aviso también lista lodash-es.
    pkg = _pkg("4.17.15", [["4.17.21"]], name="lodash")
    pkg["vulnerabilities"][0]["affected"].append(
        {
            "package": {"name": "lodash-es"},
            "ranges": [{"type": "SEMVER", "events": [{"fixed": "9.9.9"}]}],
        }
    )
    assert deps.min_fixed_version(pkg) == "4.17.21"


def test_parse_escribe_version_y_rule(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.19.0\n", encoding="utf-8")
    pkg = _pkg("2.19.0", [["2.20.0"]]) | {
        "groups": [{"ids": ["PYSEC-y", "GHSA-x"], "aliases": ["CVE-1"], "max_severity": "7.5"}]
    }
    data = {
        "results": [{"source": {"path": str(tmp_path / "requirements.txt")}, "packages": [pkg]}]
    }
    [f] = deps._parse(tmp_path, data)
    assert f.fix == "Actualiza requests a >= 2.20.0."
    assert f.rule == "GHSA-x,PYSEC-y"


def test_parse_sin_version_corregida(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.19.0\n", encoding="utf-8")
    pkg = _pkg("2.19.0", [[]]) | {"groups": [{"ids": ["GHSA-x"], "max_severity": "7.5"}]}
    data = {
        "results": [{"source": {"path": str(tmp_path / "requirements.txt")}, "packages": [pkg]}]
    }
    [f] = deps._parse(tmp_path, data)
    assert f.fix == "Actualiza requests; no hay versión corregida publicada para todos sus avisos."

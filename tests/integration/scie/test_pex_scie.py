# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import json
import os.path
import re
import subprocess
import sys
from typing import Optional

import pytest

from pex.common import is_exe
from pex.layout import Layout
from pex.orderedset import OrderedSet
from pex.scie import SciePlatform, ScieStyle
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from testing import IS_PYPY, PY_VER, make_env, run_pex_command

if TYPE_CHECKING:
    from typing import Any, Iterable, List


@pytest.mark.parametrize(
    "scie_style", [pytest.param(style, id=str(style)) for style in ScieStyle.values()]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=str(layout)) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--sh-boot"], id="ZIPAPP-sh-boot"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-sh-boot"),
    ],
)
def test_basic(
    tmpdir,  # type: Any
    scie_style,  # type: ScieStyle.Value
    layout,  # type: Layout.Value
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "cowsay.pex")
    result = run_pex_command(
        args=[
            "cowsay==5.0",
            "-c",
            "cowsay",
            "-o",
            pex,
            "--scie",
            str(scie_style),
            "--layout",
            str(layout),
        ]
        + execution_mode_args
    )
    if PY_VER < (3, 8) or IS_PYPY:
        result.assert_failure(
            expected_error_re=r".*^{message}$".format(
                message=re.escape(
                    "You selected `--scie {style}`, but none of the selected targets have "
                    "compatible interpreters that can be embedded to form a scie:\n"
                    "{target}".format(
                        style=scie_style, target=LocalInterpreter.create().render_description()
                    )
                )
            ),
            re_flags=re.DOTALL | re.MULTILINE,
        )
        return
    if PY_VER >= (3, 13):
        result.assert_failure(
            expected_error_re=(
                r".*"
                r"^Failed to build 1 scie:$"
                r".*"
                r"^Provider: No released assets found for release [0-9]{{8}} Python {version} "
                r"of flavor install_only\.$".format(version=".".join(map(str, PY_VER)))
            ),
            re_flags=re.DOTALL | re.MULTILINE,
        )
        return
    result.assert_success()

    scie = os.path.join(str(tmpdir), "cowsay")
    assert b"| PAR! |" in subprocess.check_output(args=[scie, "PAR!"], env=make_env(PATH=None))


def test_multiple_platforms(tmpdir):
    # type: (Any) -> None

    def create_scies(
        output_dir,  # type: str
        extra_args=(),  # type: Iterable[str]
    ):
        pex = os.path.join(output_dir, "cowsay.pex")
        run_pex_command(
            args=[
                "cowsay==5.0",
                "-c",
                "cowsay",
                "-o",
                pex,
                "--scie",
                "lazy",
                "--platform",
                "linux-aarch64-cp-39-cp39",
                "--platform",
                "linux-x86_64-cp-310-cp310",
                "--platform",
                "macosx-10.9-arm64-cp-311-cp311",
                "--platform",
                "macosx-10.9-x86_64-cp-312-cp312",
            ]
            + list(extra_args)
        ).assert_success()

    python_version_by_platform = {
        SciePlatform.LINUX_AARCH64: "3.9",
        SciePlatform.LINUX_X86_64: "3.10",
        SciePlatform.MACOS_AARCH64: "3.11",
        SciePlatform.MACOS_X86_64: "3.12",
    }
    assert SciePlatform.CURRENT in python_version_by_platform

    def assert_platforms(
        output_dir,  # type: str
        expected_platforms,  # type: Iterable[SciePlatform.Value]
    ):
        # type: (...) -> None

        all_output_files = set(
            path
            for path in os.listdir(output_dir)
            if os.path.isfile(os.path.join(output_dir, path))
        )
        for platform in OrderedSet(expected_platforms):
            python_version = python_version_by_platform[platform]
            binary = platform.qualified_binary_name("cowsay")
            assert binary in all_output_files
            all_output_files.remove(binary)
            scie = os.path.join(output_dir, binary)
            assert is_exe(scie), "Expected --scie build to produce a {binary} binary.".format(
                binary=binary
            )
            if platform is SciePlatform.CURRENT:
                assert b"| PEX-scie wabbit! |" in subprocess.check_output(
                    args=[scie, "PEX-scie wabbit!"], env=make_env(PATH=None)
                )
                assert (
                    python_version
                    == subprocess.check_output(
                        args=[
                            scie,
                            "-c",
                            "import sys; print('.'.join(map(str, sys.version_info[:2])))",
                        ],
                        env=make_env(PEX_INTERPRETER=1),
                    )
                    .decode("utf-8")
                    .strip()
                )
        assert {"cowsay.pex"} == all_output_files, (
            "Expected one output scie for each platform plus the original cowsay.pex. All expected "
            "scies were found, but the remaining files are: {remaining_files}".format(
                remaining_files=all_output_files
            )
        )

    all_platforms_output_dir = os.path.join(str(tmpdir), "all-platforms")
    create_scies(output_dir=all_platforms_output_dir)
    assert_platforms(
        output_dir=all_platforms_output_dir,
        expected_platforms=(
            SciePlatform.LINUX_AARCH64,
            SciePlatform.LINUX_X86_64,
            SciePlatform.MACOS_AARCH64,
            SciePlatform.MACOS_X86_64,
        ),
    )

    # Now restrict the PEX's implied natural platform set of 4 down to 2 or 3 using
    # `--scie-platform`.
    restricted_platforms_output_dir = os.path.join(str(tmpdir), "restricted-platforms")
    create_scies(
        output_dir=restricted_platforms_output_dir,
        extra_args=[
            "--scie-platform",
            "current",
            "--scie-platform",
            str(SciePlatform.LINUX_AARCH64),
            "--scie-platform",
            str(SciePlatform.LINUX_X86_64),
        ],
    )
    assert_platforms(
        output_dir=restricted_platforms_output_dir,
        expected_platforms=(
            SciePlatform.CURRENT,
            SciePlatform.LINUX_AARCH64,
            SciePlatform.LINUX_X86_64,
        ),
    )


PRINT_VERSION_SCRIPT = "import sys; print('.'.join(map(str, sys.version_info[:3])))"


skip_if_pypy = pytest.mark.skipif(IS_PYPY, reason="PyPy targeted PEXes do not support --scie.")


@skip_if_pypy
def test_specified_interpreter(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "empty.pex")
    run_pex_command(
        args=[
            "-o",
            pex,
            "--scie",
            "lazy",
            # We pick a specific version that is not in the latest release but is known to provide
            # distributions for all platforms Pex tests run on.
            "--scie-pbs-release",
            "20221002",
            "--scie-python-version",
            "3.10.7",
        ],
    ).assert_success()

    assert (
        ".".join(map(str, sys.version_info[:3]))
        == subprocess.check_output(args=[pex, "-c", PRINT_VERSION_SCRIPT]).decode("utf-8").strip()
    )

    scie = os.path.join(str(tmpdir), "empty")
    assert b"3.10.7\n" == subprocess.check_output(args=[scie, "-c", PRINT_VERSION_SCRIPT])


@skip_if_pypy
def test_specified_science_binary(tmpdir):
    # type: (Any) -> None

    pex_root = os.path.join(str(tmpdir), "pex_root")
    scie = os.path.join(str(tmpdir), "cowsay")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "cowsay==6.0",
            "-c",
            "cowsay",
            "--scie",
            "lazy",
            "--scie-python-version",
            "3.12",
            "-o",
            scie,
            "--scie-science-binary",
            # N.B.: This custom version is both lower than the latest available version (0.4.2
            # at the time of writing) and higher than the minimum supported version of 0.3.0; so
            # we can prove we downloaded the custom version via this URL by checking the version
            # below since our next floor bump will be from 0.3.0 to at least 0.4.3.
            "https://github.com/a-scie/lift/releases/download/v0.4.0/{binary}".format(
                binary=SciePlatform.CURRENT.qualified_binary_name("science")
            ),
        ],
        env=make_env(PATH=None),
    ).assert_success()

    assert b"| Alternative SCIENCE Facts! |" in subprocess.check_output(
        args=[scie, "-t", "Alternative SCIENCE Facts!"]
    )

    science_binaries = glob.glob(os.path.join(pex_root, "scies", "science", "*", "bin", "science"))
    assert 1 == len(science_binaries)
    science = science_binaries[0]
    assert "0.4.0" == subprocess.check_output(args=[science, "--version"]).decode("utf-8").strip()


@skip_if_pypy
def test_custom_lazy_urls(tmpdir):
    # type: (Any) -> None

    scie = os.path.join(str(tmpdir), "empty")
    run_pex_command(
        args=[
            "-o",
            scie,
            "--scie",
            "lazy",
            "--scie-pbs-release",
            "20221002",
            "--scie-python-version",
            "3.10.7",
        ],
    ).assert_success()

    assert b"3.10.7\n" == subprocess.check_output(args=[scie, "-c", PRINT_VERSION_SCRIPT])

    pex_bootstrap_urls = os.path.join(str(tmpdir), "pex_bootstrap_urls.json")

    def make_20221002_3_10_7_file(platform):
        # type: (str) -> str
        return "cpython-3.10.7+20221002-{platform}-install_only.tar.gz".format(platform=platform)

    def make_20240415_3_10_14_url(platform):
        # type: (str) -> str
        return (
            "https://github.com/indygreg/python-build-standalone/releases/download/20240415/"
            "cpython-3.10.14+20240415-{platform}-install_only.tar.gz".format(platform=platform)
        )

    with open(pex_bootstrap_urls, "w") as fp:
        json.dump(
            {
                "ptex": {
                    make_20221002_3_10_7_file(platform): make_20240415_3_10_14_url(platform)
                    for platform in (
                        "aarch64-apple-darwin",
                        "x86_64-apple-darwin",
                        "aarch64-unknown-linux-gnu",
                        "x86_64-unknown-linux-gnu",
                    )
                }
            },
            fp,
        )

    process = subprocess.Popen(
        args=[scie, "-c", PRINT_VERSION_SCRIPT],
        env=make_env(
            PEX_BOOTSTRAP_URLS=pex_bootstrap_urls, SCIE_BASE=os.path.join(str(tmpdir), "nce")
        ),
        stderr=subprocess.PIPE,
    )
    _, stderr = process.communicate()
    assert 0 != process.returncode, (
        "Expected PEX_BOOTSTRAP_URLS to be used and the resulting fetched interpreter distribution "
        "to fail its digest check."
    )

    expected_platform = None  # type: Optional[str]
    if SciePlatform.CURRENT is SciePlatform.LINUX_AARCH64:
        expected_platform = "aarch64-unknown-linux-gnu"
    elif SciePlatform.CURRENT is SciePlatform.LINUX_X86_64:
        expected_platform = "x86_64-unknown-linux-gnu"
    elif SciePlatform.CURRENT is SciePlatform.MACOS_AARCH64:
        expected_platform = "aarch64-apple-darwin"
    elif SciePlatform.CURRENT is SciePlatform.MACOS_X86_64:
        expected_platform = "x86_64-apple-darwin"
    assert expected_platform is not None

    assert re.match(
        r"^.*Population of work directory failed: The tar\.gz destination .*{expected_file_name} "
        r"of size \d+ had unexpected hash: [a-f0-9]{{64}}$.*".format(
            expected_file_name=re.escape(make_20221002_3_10_7_file(expected_platform))
        ),
        stderr.decode("utf-8"),
        flags=re.DOTALL | re.MULTILINE,
    ), stderr.decode("utf-8")
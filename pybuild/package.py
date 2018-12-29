import importlib
import itertools
import os.path
import pathlib
import shutil
from typing import Dict, Iterator, List, Optional, Sequence, Union
import urllib.request
import urllib.error

from .patch import Patch
from .source import Source, URLSource, VCSSource
from .util import (
    _PathType,
    android_api_level,
    BASE,
    parse_ndk_revision,
    run_in_dir,
    tar_cmd,
    target_arch,
)


class Package:
    BUILDDIR = BASE / 'build'
    DIST_PATH = BUILDDIR / 'dist'
    SYSROOT = BUILDDIR / 'sysroot'
    ARCHIVES_ROOT = 'https://dl.chyen.cc/python3-android/'

    version: Optional[str] = None
    source: Optional[Source] = None
    patches: List[Patch] = []
    dependencies: List[str] = []
    skip_uploading: bool = False

    def __init__(self):
        self.name = type(self).__name__.lower()
        self.arch = target_arch().__class__.__name__
        self.env: Dict[str, Union[_PathType, Sequence[_PathType]]] = {}
        self._ndk = None

        for f in itertools.chain(self.sources, self.patches):
            f.package = self

        for directory in (self.DIST_PATH, self.destdir(), self.SYSROOT):
            directory.mkdir(exist_ok=True, parents=True)

    def get_version(self):
        return self.version or self.source.get_version()

    @property
    def sources(self) -> List[Source]:
        ret = []
        for source in itertools.chain([self.source], self.patches):
            if source and isinstance(source, Source):
                ret.append(source)
                if source.sig_suffix:
                    ret.append(URLSource(
                        source.source_url + source.sig_suffix))
        return ret

    @classmethod
    def destdir(cls) -> pathlib.Path:
        return cls.BUILDDIR / 'target' / cls.__name__.lower()

    def init_build_env(self) -> bool:
        if self.env:
            return False

        CLANG_PREFIX = (self.unified_toolchain /
                        f'{target_arch().ANDROID_TARGET}{android_api_level()}')

        cflags = ['-fPIC']

        self.env.update({
            # Compilers
            'CC': f'{CLANG_PREFIX}-clang',
            'CXX': f'{CLANG_PREFIX}-clang++',
            'CPP': f'{CLANG_PREFIX}-clang -E',

            # Compiler flags
            'CPPFLAGS': [
                f'-I{self.SYSROOT}/usr/include',
            ],
            'CFLAGS': cflags,
            'CXXFLAGS': cflags,
            'LDFLAGS': [
                f'-L{self.SYSROOT}/usr/lib',
                '-pie',
                '-fuse-ld=lld',
            ],

            # pkg-config settings
            'PKG_CONFIG_SYSROOT_DIR': self.SYSROOT,
            'PKG_CONFIG_LIBDIR': self.SYSROOT / 'usr' / 'lib' / 'pkgconfig',
        })

        for prog in ('ar', 'as', 'ld', 'objcopy', 'objdump', 'ranlib', 'strip', 'readelf'):
            self.env[prog.upper()] = self.unified_toolchain / f'{target_arch().binutils_prefix}-{prog}'

        return True

    @property
    def filesdir(self) -> pathlib.Path:
        return BASE / 'mk' / self.name

    def need_download(self) -> bool:
        if not self.source:
            return False
        if isinstance(self.source, VCSSource):
            return True
        return not (self.source.source_dir / 'Makefile').exists()

    def run(self, cmd: List[str], *args, **kwargs) -> None:
        assert isinstance(self.source, Source)
        self.source.run_in_source_dir(cmd, *args, **kwargs)

    def run_with_env(self, cmd: List[str]) -> None:
        assert isinstance(self.source, Source)
        self.init_build_env()
        self.source.run_in_source_dir(cmd, env=self.env)

    def _check_ndk(self) -> None:
        ndk_path = os.getenv('ANDROID_NDK')
        if not ndk_path:
            raise Exception('Requires environment variable $ANDROID_NDK')
        ndk = pathlib.Path(ndk_path)

        HOST_OS = os.uname().sysname.lower()

        if HOST_OS not in ('linux', 'darwin'):
            raise Exception(f'Unsupported system {HOST_OS}')

        self.unified_toolchain = ndk / 'toolchains' / 'llvm' / 'prebuilt' / f'{HOST_OS}-x86_64' / 'bin'

        if not self.unified_toolchain.exists():
            raise Exception('Requires Android NDK r19 or above')

        self._ndk = ndk

    @property
    def ndk(self):
        if self._ndk is None:
            self._check_ndk()

        return self._ndk

    def prepare(self):
        raise NotImplementedError

    def build(self):
        raise NotImplementedError

    def create_tarball(self):
        print(f'Creating {self.tarball_name} in {self.DIST_PATH}...')

        run_in_dir([tar_cmd(), '-jcf', self.tarball_path, '.'], cwd=self.destdir())

    @property
    def tarball_name(self):
        ndk_revision = parse_ndk_revision(self.ndk)
        return f'{self.name}-{self.arch}-{self.get_version()}-android{android_api_level()}-ndk_{ndk_revision}.tar.bz2'

    @property
    def tarball_path(self):
        return self.DIST_PATH / self.tarball_name

    def upload_tarball(self):
        if self.skip_uploading:
            print(f'Skipping uploading for package {self.name}')
            return
        dest = os.getenv('PYTHON3_ANDROID_TARBALL_DEST')
        if dest:
            dest_path = pathlib.Path(dest)
            shutil.copy2(self.tarball_path, dest_path)
            # buildbot defaults to umask 077
            os.chmod(dest_path / os.path.basename(self.tarball_path), 0o644)

    def extract_tarball(self):
        run_in_dir(
            [tar_cmd(), '-jxf', self.tarball_path],
            cwd=self.SYSROOT)

    def fetch_tarball(self):
        if self.skip_uploading:
            print(f'Skipping fetching package {self.name}')
            return

        if self.tarball_path.exists():
            print(f'Skipping already downloaded {self.tarball_path}...')
            return True

        url = self.ARCHIVES_ROOT + os.path.basename(self.tarball_path)
        try:
            print(f'Downloading {url}...')
            req = urllib.request.urlopen(url)
        except urllib.error.HTTPError as err:
            if err.code == 404:
                print(f'{url} is missing. Skipping...')
                return False

            raise

        with open(self.tarball_path, 'wb') as f:
            f.write(req.read())

        self.extract_tarball()

        return True


def import_package(pkgname: str) -> Package:
    pkgmod = importlib.import_module(f'pybuild.packages.{pkgname}')
    for symbol_name in dir(pkgmod):
        symbol = getattr(pkgmod, symbol_name)
        if type(symbol) == type and symbol_name.lower() == pkgname:
            return symbol()

    raise Exception(f'Package {pkgname} not found')


def enumerate_packages() -> Iterator[str]:
    for child in (pathlib.Path(__file__).parent / 'packages').iterdir():
        pkgname, ext = os.path.splitext(os.path.basename(child))
        if ext != '.py':
            continue
        yield pkgname

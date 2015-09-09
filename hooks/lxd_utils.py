import glob
import pwd
import os

from subprocess import call, check_call

from charmhelpers.core.templating import render
from charmhelpers.core.hookenv import (
    log,
    config,
    ERROR,
)
from charmhelpers.core.host import (
    add_group,
    add_user_to_group,
    mkdir,
    mount,
)
from charmhelpers.contrib.storage.linux.utils import (
    is_block_device,
)
from charmhelpers.contrib.storage.linux.loopback import (
    ensure_loopback_device
)
from charmhelpers.contrib.storage.linux.lvm import (
    create_lvm_volume_group,
    create_lvm_physical_volume
)

BASE_PACKAGES = ['btrfs-tools', 'lvm2']
LXD_PACKAGES = ['lxd', 'lxd-client']
LXD_SOURCE_PACKAGES = [
    'lxc',
    'lxc-dev',
    'mercurial',
    'git',
    'pkg-config',
    'protobuf-compiler',
    'golang-goprotobuf-dev',
    'build-essential',
    'golang',
    'xz-utils',
    'tar',
    'acl',
]

LXD_GIT = 'github.com/lxc/lxd'
DEFAULT_LOOPBACK_SIZE = '10G'


def install_lxd():
    '''Install LXD'''


def install_lxd_source(user='ubuntu'):
    '''Install LXD from source repositories; installs toolchain first'''
    log('Installing LXD from source')

    home = pwd.getpwnam(user).pw_dir
    GOPATH = os.path.join(home, 'go')
    LXD_SRC = os.path.join(GOPATH, 'src', 'github.com/lxc/lxd')

    if not os.path.exists(GOPATH):
        mkdir(GOPATH)

    env = os.environ.copy()
    env['GOPATH'] = GOPATH
    env['HTTP_PROXY'] = 'http://squid.internal:3128'
    env['HTTPS_PROXY'] = 'https://squid.internal:3128'
    cmd = 'go get -v %s' % LXD_GIT
    log('Installing LXD: %s' % (cmd))
    check_call(cmd, env=env, shell=True)

    if not os.path.exists(LXD_SRC):
        log('Failed to go get %s' % LXD_GIT, level=ERROR)
        raise

    cwd = os.getcwd()
    try:
        os.chdir(LXD_SRC)
        cmd = 'go get -v -d ./...'
        log('Downloading LXD deps: %s' % (cmd))
        call(cmd, env=env, shell=True)

        # build deps
        cmd = 'make'
        log('Building LXD deps: %s' % (cmd))
        call(cmd, env=env, shell=True)
    except Exception:
        log("failed to install lxd")
        raise
    finally:
        os.chdir(cwd)


def configure_lxd_source(user='ubuntu'):
    '''Add required configuration and files when deploying LXD from source'''
    log('Configuring LXD Source')
    home = pwd.getpwnam(user).pw_dir
    GOPATH = os.path.join(home, 'go')

    templates_dir = 'templates'
    render('lxd_upstart', '/etc/init/lxd.conf', {},
           perms=0o644, templates_dir=templates_dir)
    render('lxd_service', '/lib/systemd/system/lxd.service', {},
           perms=0o644, templates_dir=templates_dir)
    add_group('lxd', system_group=True)
    add_user_to_group(user, 'lxd')

    files = glob.glob('%s/bin/*' % GOPATH)
    for i in files:
        cmd = ['cp', i, '/usr/bin']
        check_call(cmd)


def configure_lxd_block():
    '''Configure a block device for use by LXD for containers'''
    log('Configuring LXD container storage')
    if filesystem_mounted('/var/lib/lxd'):
        log('/varlib/lxd already configured, skipping')
        return

    lxd_block_device = config('block-device')
    if not lxd_block_device:
        log('block device is not provided - skipping')
        return

    dev = None
    if lxd_block_device.startswith('/dev/'):
        dev = lxd_block_device
    elif lxd_block_device.startswith('/'):
        log('Configuring loopback device for use with LXD')
        _bd = lxd_block_device.split('|')
        if len(_bd) == 2:
            dev, size = _bd
        else:
            dev = lxd_block_device
            size = DEFAULT_LOOPBACK_SIZE
        dev = ensure_loopback_device(dev, size)

    if not dev or not is_block_device(dev):
        log('Invalid block device provided: %s' % lxd_block_device)
        return

    if not os.path.exists('/var/lib/lxd'):
        mkdir('/var/lib/lxd')

    if config('fs-type') == 'btrfs':
        cmd = ['mkfs.btrfs', '-f', dev]
        check_call(cmd)
        mount(dev,
              '/var/lib/lxd',
              options='user_subvol_rm_allowed',
              persist=True,
              filesystem='btrfs')
    elif config('fs-type') == 'lvm':
        create_lvm_physical_volume(dev)
        create_lvm_volume_group('lxd_vg', dev)


def determine_packages():
    packages = [] + BASE_PACKAGES
    packages = list(set(packages))
    if config('use-source'):
        packages.extend(LXD_SOURCE_PACKAGES)
    else:
        packages.extend(LXD_PACKAGES)
    return packages


def filesystem_mounted(fs):
    return call(['grep', '-wqs', fs, '/proc/mounts']) == 0

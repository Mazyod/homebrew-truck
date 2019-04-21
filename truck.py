#!/usr/local/bin/python3
"""
Truck - a straight-forward dependency/binary manager
this file contains both the client and authoring tools.
"""
import sys
import os
import re
import json
import time
import zipfile
import shutil
import urllib
import hashlib
from collections import OrderedDict
from urllib.request import FancyURLopener, urlopen
from distutils.version import LooseVersion


####
# Global configuration / constants
#

TRUCK_VERSION = "0.7.7"

TRUCK_ROOT_DIRECTORY = "Truck"
TRUCK_TMP_DIRECTORY = os.path.join(TRUCK_ROOT_DIRECTORY, "Tmp")

TRUCK_SECRETS_TEMPLATE = {
    "SWIFT_VERSION_OVERRIDE": "",
    "GITHUB_TOKEN": ""
}

TRUCK_AUTHOR_TEMPLATE = {
    "github": {
        "user": "",
        "repo": ""
    }
}

TRUCK_SPEC_FILENAME = "{target}-spec.json"
TARGET_CONFIG_FILEPATH = "{target}-config.json"


####
# Basic Entities
#

class DownloadCache:
    def __init__(self):
        self.cache_dir = os.path.expanduser("~/Library/Caches/truck")

    @property
    def downloads_dir(self):
        path = os.path.join(self.cache_dir, "downloads")
        os.makedirs(path, exist_ok=True)
        return path

    def key_for_url(self, url):
        hashfun = hashlib.md5()
        hashfun.update(url.encode())
        return hashfun.hexdigest()

    def cache_path_for_url(self, url):
        key = self.key_for_url(url)
        return os.path.join(self.downloads_dir, key)

    def nuke(self):
        try:
            shutil.rmtree(self.downloads_dir)
        except:
            pass

    def store(self, url, payload_path):
        cache_path = self.cache_path_for_url(url)
        try:
            shutil.copy2(payload_path, cache_path)
            print(f"Cached {payload_path} -> {cache_path}")
        except Exception as e:
            print(e)
            print(f"Caching {payload_path} -> {cache_path} failed")

    def fetch_to(self, url, dst):
        cache_path = self.cache_path_for_url(url)
        if os.path.exists(cache_path):
            print(f"Cache hit! {url}")
            shutil.copy2(cache_path, dst)
            return True
        else:
            print(f"Cache miss {url}")
            return False

def reporthook(count, block_size, total_size):
    global start_time

    if count == 0:
        start_time = time.time()
        return

    duration = time.time() - start_time
    progress_size = int(count * block_size)
    speed = int(progress_size / (1024 * duration))
    percent = int(count * block_size * 100 / total_size)

    sys.stdout.write('\x1b[2K\r')
    sys.stdout.write("... %d%%, %d MB, %d KB/s, %d seconds passed" %
                    (percent, progress_size / (1024 * 1024), speed, duration))
    sys.stdout.flush()

def download(url, filename, check_cache=True):
    cache = DownloadCache()
    hit = check_cache and cache.fetch_to(url, filename)
    if hit:
        return

    url_session = FancyURLopener()

    try:
        url_session.retrieve(url, filename, reporthook=reporthook)
    except Exception as e:
        print("warning: {} failed to download".format(url))
        print(e)
        return

    sys.stdout.write('\x1b[2K\r')
    sys.stdout.write("... Downloaded " + filename + "\n")
    sys.stdout.flush()

    cache.store(url, filename)

def simple_download(url):
    req = urlopen(url)
    return req.read()

def precondition(cond=False, msg=""):
    if not cond:
        print(msg)
        exit(1)

class PathUtils:

    # file operations
    @classmethod
    def open_or_create_json_file(cls, filepath, template):

        if not os.path.exists(filepath):
            cls.write_json_file(filepath, template)

        with open(filepath) as f:
            content = json.loads(f.read())

        return content

    @classmethod
    def write_json_file(cls, filepath, config):
        with open(filepath, "w+") as f:
            f.write(json.dumps(config, indent=2) + "\n")


class TruckAction:

    @staticmethod
    def print_actions(actions):
        print("\n".join([str(a) for a in actions]))

    def __init__(self, name, arg_count, eg, description, callback):
        self.name = name
        self.arg_count = arg_count
        self.eg = eg
        self.description = description
        self.callback = callback

    def __str__(self):
        return self.name + " - " + self.description + " (e.g. " + self.eg + ")"

    def trigger(self, args):

        if isinstance(self.arg_count, int):
            range_ = [self.arg_count]
        else:
            range_ = self.arg_count

        if len(args) not in range_:
            precondition(msg=f"{self.name} expects {self.arg_count} arguments")

        self.callback(*args)


class TruckDep:
    def __init__(self, version=None, url=None, name=None):
        # version and url provided from truck.json, while name is provided for
        # deps that are downloaded and enumerated from disk
        precondition(bool(version and url) != bool(name), "URL xor name required")
        # in case the version is provided from truck.json, let's allow for the
        # user to override the Swift version outside of git
        processed_version = version and Truck.process_version(version)

        self.spec_url = url
        self.name = name or os.path.splitext(self.spec_filename)[0]

        self.old_spec = self.load_old_spec()
        self.version = processed_version or self.old_spec["version"]
        # keep raw version handy in case we need to write to truck.json
        self.raw_version = version

        self.spec_json = {}
        self.binary_filelist = []

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"{self.name} ({self.version})"

    @property
    def binary_url(self):
        return self.spec_json[self.version]

    @property
    def spec_filename(self):
        return os.path.basename(self.spec_url)

    @property
    def binary_filename(self):
        return os.path.basename(self.binary_url)

    @property
    def version_filepath(self):
        return os.path.join(TRUCK_ROOT_DIRECTORY, self.name + ".version")

    @property
    def spec_path(self):
        return os.path.join(TRUCK_TMP_DIRECTORY, self.spec_filename)

    @property
    def binary_path(self):
        return os.path.join(TRUCK_TMP_DIRECTORY, self.binary_filename)

    @property
    def binary_zipfile(self):
        return zipfile.ZipFile(self.binary_path, 'r')

    @property
    def extraction_path(self):
        return TRUCK_ROOT_DIRECTORY

    @property
    def json(self):
        # let's guarantee the key order
        return OrderedDict({"url": self.spec_url, "version": self.raw_version})

    @property
    def is_out_of_sync(self):
        if not os.path.isfile(self.version_filepath):
            return True

        with open(self.version_filepath) as f:
            meta = json.loads(f.read())

        return meta["version"] != self.version

    def update_version(self, new_version):
        # make sure to change raw_version only, this is for disk needs only
        self.raw_version = new_version

    def load_old_spec(self):
        if not os.path.isfile(self.version_filepath):
            return None

        with open(self.version_filepath) as f:
            return json.loads(f.read())

    def download_spec(self, check_cache=True):
        download(self.spec_url, self.spec_path, check_cache)

        with open(self.spec_path) as f:
            try:
                self.spec_json = json.loads(f.read())
            except:
                self.spec_json = {}

        # check if spec json is missing the spec version
        # if it is, we need to check remote for a newer version
        try:
            _ = self.binary_url
        except KeyError:
            if check_cache:
                print("Possible stale spec cache...")
                self.download_spec(False)
            else:
                raise

    def download_binary(self):
        download(self.binary_url, self.binary_path)
        all_files = self.binary_zipfile.namelist()
        top_level = set([f.split("/")[0] for f in all_files])
        self.binary_filelist = list(top_level)


class ClientConfig:
    def __init__(self, json, filepath):
        self.deps = [TruckDep(**dep) for dep in json]
        self.filepath = filepath

    def set_target_version(self, target, version):
        for dep in self.deps:
            if dep.name == target:
                dep.update_version(version)
                self.write_to_file()
                break
        else:
            print(f"Warning: Couldn't find {target} in truck.json")

    def write_to_file(self):
        with open(self.filepath, "w+") as f:
            raw = [d.json for d in self.deps]
            f.write(json.dumps(raw, indent=2) + "\n")


class Truck:
    SECRETS = None

    @classmethod
    def secrets(cls):
        if cls.SECRETS:
            return cls.SECRETS

        truck_secrets_filepath = os.path.expanduser("~/.truckrc")
        cls.SECRETS = PathUtils.open_or_create_json_file(
            truck_secrets_filepath, TRUCK_SECRETS_TEMPLATE
        )

        return cls.SECRETS

    @classmethod
    def process_version(cls, version):
        swift_override = cls.secrets().get("SWIFT_VERSION_OVERRIDE")
        if not swift_override:
            return version
        regex = re.compile(r"\d+(\.\d+)+-\d+(\.\d+)+-\d+(\.\d+)+$")
        return regex.sub(swift_override, version)

####
# Truck client implementation
#
# The client allows users to either sync or pull dependencies defined by the
# truck.json file.
#

class TruckClient:

    def __init__(self):
        self.truck_config = self.load_client_config()
        self.deps_on_disk = self.load_deps_on_disk()
        self.actions = [
            TruckAction(
                "list",
                0,
                "truck list",
                "list the downloaded deps",
                self.perform_list_action
            ),
            TruckAction(
                "sync",
                0,
                "truck sync",
                "downloads deps if neccessary",
                self.perform_sync_action
            ),
            TruckAction(
                "pull",
                0,
                "truck pull",
                "download all deps regardless of local cache",
                self.perform_sync_action
            ),
            TruckAction(
                "check",
                0,
                "truck check",
                "check if sync is required printing either ok or error",
                self.perform_check_action
            ),
            TruckAction(
                "clean",
                1,
                "truck clean nonexistent",
                "deletes target's files or send in existent/nonexistent",
                self.perform_clean_action
            ),
            TruckAction(
                "version",
                0,
                "truck version",
                "print version and exit",
                self.perform_version_action
            ),
            TruckAction(
                "nuke_cache",
                0,
                "truck nuke_cache",
                "nukes download cache",
                self.perform_nuke_cache_action
            ),
            TruckAction(
                "set_version",
                2,
                "truck set_version zendesk 3.0.1",
                "set the version of a given target in truck.json",
                self.perform_set_version_action
            ),
        ]

    def assert_truck_config_available(self):
        if not self.truck_config:
            precondition(msg=f"Cannot find truck.json in local directory!")

    def load_client_config(self):
        config_filename = "truck.json"
        if not os.path.isfile(config_filename):
            return None

        with open(config_filename) as f:
            client_json = json.loads(f.read())

        return ClientConfig(client_json, config_filename)

    def load_deps_on_disk(self):
        if not os.path.isdir(TRUCK_ROOT_DIRECTORY):
            return []
        all_files = os.listdir(TRUCK_ROOT_DIRECTORY)
        ver_files = [fname for fname in all_files if fname.endswith(".version")]
        target_names = [os.path.splitext(f)[0] for f in ver_files]
        return [TruckDep(name=n) for n in target_names]

    def clean_deps(self, deps, protected_files):
        print("Cleaning:")
        print("\n".join([str(dep) for dep in deps]))

        for dep in deps:
            self.clean_extraction_path(dep, protected_files)

    def clean_temp_folder(self):
        try:
            shutil.rmtree(TRUCK_TMP_DIRECTORY)
        except:
            pass

        os.makedirs(TRUCK_TMP_DIRECTORY)

    def clean_extraction_path(self, dep, protected_files=set()):
        if not dep.old_spec:
            return

        for f in dep.old_spec["files"]:
            if f in protected_files:
                continue
            filepath = os.path.join(TRUCK_ROOT_DIRECTORY, f)
            try:
                if os.path.isfile(filepath):
                    os.remove(filepath)
                else:
                    shutil.rmtree(filepath)
            except:
                print("warning: failed to remove " + filepath)

        os.remove(dep.version_filepath)

    def download_binary_and_spec(self, dep):
        dep.download_spec()
        dep.download_binary()

    def extract_archive(self, dep):
        zref = dep.binary_zipfile
        zref.extractall(dep.extraction_path)
        zref.close()

    def pin_version(self, dep):
        with open(dep.version_filepath, "w+") as f:
            f.write(json.dumps({
                "version": dep.version,
                "files": dep.binary_filelist
            }))

    def fetch_deps(self, deps):

        if not deps:
            print("All deps are up to date!")
            return

        print("Updating:")
        print("\n".join([str(dep) for dep in deps]))

        self.clean_temp_folder()

        for dep in deps:
            self.download_binary_and_spec(dep)
            self.clean_extraction_path(dep)
            self.extract_archive(dep)
            self.pin_version(dep)
            print(dep.name + " synced!")

        self.clean_temp_folder()

    def perform_list_action(self):
        self.assert_truck_config_available()
        print("\n".join([str(dep) for dep in sorted(self.deps_on_disk, key=lambda x: x.name)]))

    def perform_sync_action(self):
        self.assert_truck_config_available()
        deps = [dep for dep in self.truck_config.deps if dep.is_out_of_sync]
        self.fetch_deps(deps)

    def perform_pull_action(self):
        self.assert_truck_config_available()
        self.fetch_deps(self.truck_config.deps)

    def perform_check_action(self):
        self.assert_truck_config_available()
        deps = [dep for dep in self.truck_config.deps if dep.is_out_of_sync]
        print("error" if deps else "ok")

    def perform_clean_action(self, target):
        self.assert_truck_config_available()

        deps = self.deps_on_disk
        protected_files = set()
        if target == "nonexistent":
            existent_names = [d.name for d in self.truck_config.deps]
            deps = [d for d in deps if d.name not in existent_names]
            old_specs = [d.old_spec for d in self.truck_config.deps if d.old_spec]
            protected_files = set([f for s in old_specs for f in s["files"]])
        elif target != "all":
            deps = [d for d in deps if d.name.lower() == target.lower()]
        self.clean_deps(deps, protected_files)

    def perform_version_action(self):
        print(TRUCK_VERSION)

    def perform_nuke_cache_action(self):
        cache = DownloadCache()
        cache.nuke()

    def perform_set_version_action(self, target, new_version):
        self.truck_config.set_target_version(target, new_version)


####
# TruckAuthor
#
# The authoring tool used to generate and publish dependency target
# specifications.
#

class Hosting:

    def __init__(self, config):
        self.config = config or {}
        self.hosts = []

        if "github" in self.config:
            self.hosts.append(GithubHost(config))

    @property
    def active_hosting(self):
        hosts = self.all()
        if not hosts:
            precondition("Please populate truck-author.json with a supported host")
        return hosts[0]

    def all(self):
        return self.hosts

    def find_spec(self, target):
        spec = {}
        for host in self.all():
            try:
                json_http_uri = host.spec_http_uri(target)
                spec_data = simple_download(json_http_uri)
                spec.update(json.loads(spec_data))
            except:
                pass

        return spec

class GithubHost:
    def __init__(self, config):
        self.user = config["github"]["user"]
        self.repo = config["github"]["repo"]
        self.base_path = "https://github.com/{user}/{repo}/releases/download/truck".format(
            user=self.user,
            repo=self.repo
        )

    # path definitions

    ## uri builders
    def build_http_uri(self, path):
        return os.path.join(self.base_path, path)

    ## spec uris
    def spec_http_uri(self, target):
        spec_path = "{t}.json".format(t=target)
        return self.build_http_uri(spec_path)

    ## binary uris
    def binary_http_uri(self, target, version):
        binary_path = "{t}-{v}.zip".format(t=target, v=version)
        return self.build_http_uri(binary_path)

    # actions

    def upload_file(self, name, local_path):

        upload_command = " ".join(map(lambda i: "=".join(i), Truck.secrets().items()))
        upload_command += (
            ' github-release upload --replace'
            ' -u {user}'
            ' -r {repo}'
            ' -t truck'
            ' -n {name}'
            ' -f {file}'
        ).format(user=self.user, repo=self.repo, name=name, file=local_path)

        os.system(upload_command)

    def publish(self, target, version, spec_filepath, archive_filepath):
        # TODO - possibly fallback to env to find the keys
        if "GITHUB_TOKEN" not in Truck.secrets():
            print("Could not find Github token in config nor env")
            print("Please fill them in ~/.truckrc")
            exit(1)

        print("Uploading to Github ...")

        spec_name = f'{target}.json'
        self.upload_file(spec_name, spec_filepath)

        if archive_filepath:
            binary_name = f'{target}-{version}.zip'
            self.upload_file(binary_name, archive_filepath)


class TruckAuthor:
    def __init__(self):
        self.config = self.load_author_config()
        self.hosting = Hosting(self.config)
        self.actions = [
            TruckAction(
                "init",
                0,
                "truck init",
                "creates a template truck-author.json",
                self.perform_init_action
            ),
            TruckAction(
                "add",
                2,
                "truck add zendesk-sdk path/to/file",
                "adds a file to target configuration",
                self.perform_add_action
            ),
            TruckAction(
                "release",
                range(1, 3),
                "truck release zendesk-sdk [3.0.2]",
                "packages then uploads a release for given target",
                self.perform_release_action
            ),
            TruckAction(
                "versions",
                1,
                "truck versions zendesk-sdk",
                "prints comma separated list of versions for target",
                self.perform_versions_action
            ),
            TruckAction(
                "reset",
                1,
                "truck reset zendesk-sdk",
                "deletes the spec json config",
                self.perform_reset_action
            ),
            TruckAction(
                "rmversion",
                2,
                "truck rmversion zendesk-sdk 1.1.0",
                "removes the specified version from remote",
                self.perform_rmversion_action
            )
        ]

    def load_author_config(self):
        config_filename = "truck-author.json"
        if not os.path.isfile(config_filename):
            return None

        with open(config_filename) as f:
            author_json = json.loads(f.read())

        return author_json

    def assert_truck_config_available(self):
        if not self.config:
            print("Cannot find {} in local directory!".format(config_filename))
            print("Try running from correct dir, or run truck init")
            exit(1)


    def infer_target_version(self, spec_json):

        versions = spec_json.keys()
        versions = sorted(versions, key=lambda x: LooseVersion(x))

        if not versions:
            return "1.0.0"

        max_version = versions[-1]
        split_version = max_version.split(".")
        split_version[-1] = str(int(split_version[-1]) + 1)
        return ".".join(split_version)

    def prepare_staging_area(self, root_dir, files):

        try:
            shutil.rmtree(root_dir)
        except:
            pass

        files_dir = os.path.join(root_dir, "files")
        os.makedirs(files_dir)

        for f in files:
            if os.path.isdir(f):
                shutil.copytree(f, os.path.join(files_dir, os.path.basename(f)))
            else:
                shutil.copyfile(f, os.path.join(files_dir, os.path.basename(f)))

        return files_dir

    def perform_reset_action(self, target):
        self.assert_truck_config_available()

        filepath = target + "-config.json"
        try:
            os.remove(filepath)
            print(filepath + " removed")

        except:
            print("warning: {} not found".format(filepath))

    def perform_versions_action(self, target):
        self.assert_truck_config_available()

        spec_json = self.hosting.find_spec(target)
        if spec_json:
            versions = ", ".join(spec_json.keys())
            print(versions)
        else:
            print("None")

    def perform_init_action(self):
        PathUtils.open_or_create_json_file("truck-author.json", TRUCK_AUTHOR_TEMPLATE)

    def perform_add_action(self, target, path):
        # load it just to make sure user is in the correct dir
        self.assert_truck_config_available()

        # workaround adding directories with trailing slash
        path = path[:-1] if path.endswith("/") else path

        if not os.path.exists(path):
            precondition(f"{path} doesn't exist!")

        filepath = target + "-config.json"
        config = PathUtils.open_or_create_json_file(filepath, {"files":[]})

        if path not in config["files"]:
            config["files"] += [path]
        else:
            print("warning: {} already exists in config".format(path))

        PathUtils.write_json_file(filepath, config)

    def perform_rmversion_action(self, target, version):
        self.assert_truck_config_available()

        spec_json = self.hosting.find_spec(target)
        if not spec_json:
            print(f"Failed to find a json spec for target {target}")
            exit(1)

        try:
            file_url = spec_json.pop(version)
        except KeyError:
            print(f"Failed to find version {version}!")
            exit(1)

        # TODO: duplicate code, consolidate me please
        files_dir = self.prepare_staging_area(TRUCK_TMP_DIRECTORY, [])
        # write spec to temp file so we can upload it
        spec_filename = TRUCK_SPEC_FILENAME.format(target=target)
        spec_filepath = os.path.join(TRUCK_TMP_DIRECTORY, spec_filename)
        PathUtils.write_json_file(spec_filepath, spec_json)

        host = self.hosting.active_hosting
        host.publish(target, version, spec_filepath, None)
        print(f"{target} -> {version} should be removed!")


    def perform_release_action(self, target, version=None):
        self.assert_truck_config_available()

        # load the target config file
        target_config_filepath = TARGET_CONFIG_FILEPATH.format(target=target)
        if not os.path.isfile(target_config_filepath):
            print(f"Can't find: {target_config_filepath}")
            print(f"Please run: truck add {target} path/to/stuff")
            exit(1)

        with open(target_config_filepath) as f:
            config_json = json.loads(f.read())

        # prepare staging area
        staging_dir = TRUCK_TMP_DIRECTORY
        files_dir = self.prepare_staging_area(staging_dir, config_json["files"])

        # add new version to spec json
        host = self.hosting.active_hosting

        spec_json = self.hosting.find_spec(target)
        version = version or self.infer_target_version(spec_json)
        spec_json[version] = host.binary_http_uri(target, version)

        # write spec to temp file so we can upload it
        spec_filename = TRUCK_SPEC_FILENAME.format(target=target)
        spec_filepath = os.path.join(TRUCK_TMP_DIRECTORY, spec_filename)
        PathUtils.write_json_file(spec_filepath, spec_json)

        shutil.make_archive(os.path.join(staging_dir, target), 'zip', files_dir)
        archive_filepath = os.path.join(staging_dir, target + ".zip")

        print("Created {}".format(archive_filepath))

        host.publish(target, version, spec_filepath, archive_filepath)

        json_http_uri = host.spec_http_uri(target)
        binary_http_uri = host.binary_http_uri(target, version)

        print("Done! {} -> {}".format(target, version))
        print("Updated {}".format(json_http_uri))
        print("Created {}".format(binary_http_uri))


####
# Entrypoint
#

def main():

    args = sys.argv[1:]
    command = args[0] if args else "bad"

    truck_client = TruckClient()
    truck_author = TruckAuthor()

    all_actions = truck_client.actions + truck_author.actions
    all_action_names = [a.name for a in all_actions]
    selected_action = [a for a in all_actions if a.name == command]

    if not selected_action:
        print("Please choose an action:")
        print("Client:")
        TruckAction.print_actions(truck_client.actions)
        print("Author:")
        TruckAction.print_actions(truck_author.actions)
        exit(1)

    selected_action[0].trigger(args[1:])


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Truck - a straight-forward dependency/binary manager
this file contains both the client and authoring tools.
"""
import sys
import os
import json
import time
import zipfile
import shutil
import urllib
from urllib.request import FancyURLopener, urlopen
from distutils.version import LooseVersion


####
# Global configuration / constants
#

TRUCK_VERSION = "0.4.1"

TRUCK_ROOT_DIRECTORY = "Truck"
TRUCK_TMP_DIRECTORY = os.path.join(TRUCK_ROOT_DIRECTORY, "Tmp")

TRUCK_SECRETS_TEMPLATE = {
    "AWS_ACCESS_KEY_ID": "",
    "AWS_SECRET_ACCESS_KEY": ""
}

TRUCK_AUTHOR_TEMPLATE = {
    "aws": {
        "s3_base_path": "",
        "default_region": "eu-west-1"
    }
}

TRUCK_SPEC_FILENAME = "{target}-spec.json"
TARGET_CONFIG_FILEPATH = "{target}-config.json"


####
# Basic Entities
#

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

def download(url, filename):
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

def simple_download(url):
    req = urlopen(url)
    return req.read()


class S3Util:

    def __init__(self, author_config):
        config = author_config["aws"]
        self.region = config["default_region"]

        base_path = config["s3_base_path"]
        start = 1 if base_path.startswith("/") else 0
        self.s3_base_path = base_path[start:]

    ## uri builders
    def build_path(self, subpath):
        return os.path.join(self.s3_base_path, subpath)

    def build_http_uri(self, path):
        host = "https://s3-{}.amazonaws.com/".format(self.region)
        return os.path.join(host, path)

    def build_s3_uri(self, path):
        return os.path.join("s3://", path)

    ## spec uris
    def spec_path(self, target):
        return self.build_path("{t}.json".format(t=target))

    def spec_http_uri(self, target):
        return self.build_http_uri(self.spec_path(target))

    def spec_s3_uri(self, target):
        return self.build_s3_uri(self.spec_path(target))

    ## binary uris
    def binary_path(self, target, version):
        return self.build_path("{t}/{v}/{t}.zip".format(t=target, v=version))

    def binary_http_uri(self, target, version):
        return self.build_http_uri(self.binary_path(target, version))

    def binary_s3_uri(self, target, version):
        return self.build_s3_uri(self.binary_path(target, version))


class OldStructure:

    @classmethod
    def create_if_present(cls, name):
        struct = OldStructure(name)
        if not os.path.isfile(struct.version_filepath):
            return None

        struct.build_object()
        return struct

    def __init__(self, name):
        self.name = name
        self.base_dir = TRUCK_ROOT_DIRECTORY
        self.version = "0.0.0"
        self.filelist = []

    @property
    def root_dir(self):
        return os.path.join(self.base_dir, self.name)

    @property
    def version_filepath(self):
        return os.path.join(self.root_dir, self.name + ".version")

    def build_object(self):
        all_files = os.listdir(self.root_dir)
        ignored = [".DS_Store"]
        self.filelist = [f for f in all_files if f not in ignored]

        with open(self.version_filepath) as f:
            self.version = f.read()

    def rewrite_version_file(self):
        with open(self.version_filepath, "w+") as f:
            f.write(json.dumps({
                "version": self.version,
                "files": self.filelist
            }))


class Migrator:
    @classmethod
    def perform_migration(cls, truck_config):

        if not os.path.isdir(TRUCK_ROOT_DIRECTORY):
            return

        # 1. create OldStructure objects
        folders = os.listdir(TRUCK_ROOT_DIRECTORY)
        possible_items = map(OldStructure.create_if_present, folders)
        items = [i for i in possible_items if i is not None]

        # 2. move them to staging area
        staging_dir = os.path.join(TRUCK_ROOT_DIRECTORY, "migration-staging")

        try:
            shutil.rmtree(staging_dir)
        except:
            pass

        os.makedirs(staging_dir)

        for struct in items:
            struct.rewrite_version_file()
            shutil.move(struct.root_dir, staging_dir)
            struct.base_dir = staging_dir

            files = os.listdir(struct.root_dir)
            for f in files:
                filepath = os.path.join(struct.root_dir, f)
                try:
                    shutil.move(filepath, TRUCK_ROOT_DIRECTORY)
                except Exception as e:
                    print("warning: failed to move " + filepath)
                    print(e)

        shutil.rmtree(staging_dir)


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
            print("{} expects {} arguments".format(self.name, self.arg_count))
            exit(1)

        self.callback(*args)


class TruckDep:
    def __init__(self, version, url):
        self.version = version
        self.spec_url = url
        self.spec_json = {}
        self.binary_filelist = []
        self.old_spec = self.load_old_spec()

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
    def name(self):
        return os.path.splitext(self.spec_filename)[0]

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
    def is_outdated(self):
        if not os.path.isfile(self.version_filepath):
            return True

        with open(self.version_filepath) as f:
            meta = json.loads(f.read())

        return meta["version"] != self.version

    def load_old_spec(self):
        if not os.path.isfile(self.version_filepath):
            return None

        with open(self.version_filepath) as f:
            return json.loads(f.read())

    def download_spec(self):
        download(self.spec_url, self.spec_path)

        with open(self.spec_path) as f:
            try:
                self.spec_json = json.loads(f.read())
            except:
                self.spec_json = {}

    def download_binary(self):
        download(self.binary_url, self.binary_path)
        all_files = self.binary_zipfile.namelist()
        top_level = set([f.split("/")[0] for f in all_files])
        self.binary_filelist = list(top_level)


class ClientConfig:
    def __init__(self, json):
        self.deps = map(lambda dep: TruckDep(**dep), json)


####
# Truck client implementation
#
# The client allows users to either sync or pull dependencies defined by the
# truck.json file.
#

class TruckClient:

    def __init__(self):
        self.truck_config = self.load_client_config()
        self.perform_migration_if_needed()
        self.actions = [
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
                "ckeck if sync is required printing either ok or error",
                self.perform_check_action
            ),
            TruckAction(
                "version",
                0,
                "truck version",
                "print version and exit",
                self.perform_version_action
            )
        ]

    def perform_migration_if_needed(self):
        if not self.truck_config:
            return

        Migrator.perform_migration(self.truck_config)

    def assert_truck_config_available(self):
        if not self.truck_config:
            print("Cannot find {} in local directory!".format(config_filename))
            exit(1)

    def load_client_config(self):
        config_filename = "truck.json"
        if not os.path.isfile(config_filename):
            return None

        with open(config_filename) as f:
            client_json = json.loads(f.read())

        return ClientConfig(client_json)

    def clean_temp_folder(self):
        try:
            shutil.rmtree(TRUCK_TMP_DIRECTORY)
        except:
            pass

        os.makedirs(TRUCK_TMP_DIRECTORY)

    def clean_extraction_path(self, dep):
        if not dep.old_spec:
            return

        for f in dep.old_spec["files"]:
            filepath = os.path.join(TRUCK_ROOT_DIRECTORY, f)
            try:
                if os.path.isfile(filepath):
                    os.remove(filepath)
                else:
                    shutil.rmtree(filepath)
            except:
                print("warning: failed to remove " + filepath)

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
        print("\n".join([dep.name for dep in deps]))

        self.clean_temp_folder()

        for dep in deps:
            self.download_binary_and_spec(dep)
            self.clean_extraction_path(dep)
            self.extract_archive(dep)
            self.pin_version(dep)
            print(dep.name + " synced!")

        self.clean_temp_folder()

    def perform_sync_action(self):
        self.assert_truck_config_available()
        deps = [dep for dep in self.truck_config.deps if dep.is_outdated]
        self.fetch_deps(deps)

    def perform_pull_action(self):
        self.assert_truck_config_available()
        self.fetch_deps(self.truck_config.deps)

    def perform_check_action(self):
        self.assert_truck_config_available()
        deps = [dep for dep in self.truck_config.deps if dep.is_outdated]
        print("error" if deps else "ok")

    def perform_version_action(self):
        print(TRUCK_VERSION)

####
# TruckAuthor
#
# The authoring tool used to generate and publish dependency target
# specifications.
#

class TruckAuthor:
    def __init__(self):
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
            )
        ]

    def load_author_config(self):
        config_filename = "truck-author.json"
        if not os.path.isfile(config_filename):
            print("Cannot find {} in local directory!".format(config_filename))
            print("Try running from correct dir, or run truck init")
            exit(1)

        with open(config_filename) as f:
            author_json = json.loads(f.read())

        return author_json


    def infer_target_version(self, spec_json):

        versions = spec_json.keys()
        versions = sorted(versions, key=lambda x: LooseVersion(x))

        if not versions:
            return "1.0.0"

        max_version = versions[-1]
        split_version = max_version.split(".")
        split_version[-1] = str(int(split_version[-1]) + 1)
        return ".".join(split_version)

    def open_or_create_json_file(self, filepath, template):

        if not os.path.exists(filepath):
            self.write_json_file(filepath, template)

        with open(filepath) as f:
            content = json.loads(f.read())

        return content

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


    def write_json_file(self, filepath, config):
        with open(filepath, "w+") as f:
            f.write(json.dumps(config, indent=2) + "\n")

    def perform_reset_action(self, target):
        # load it just to make sure user is in the correct dir
        self.load_author_config()

        filepath = target + "-config.json"
        try:
            os.remove(filepath)
            print(filepath + " removed")

        except:
            print("warning: {} not found".format(filepath))

    def perform_versions_action(self, target):
        config = self.load_author_config()
        s3util = S3Util(config)

        try:
            json_http_uri = s3util.spec_http_uri(target)
            spec_data = simple_download(json_http_uri)
            spec_json = json.loads(spec_data)
            versions = ", ".join(spec_json.keys())

            print(versions)

        except:
            print("None")

    def perform_init_action(self):
        self.open_or_create_json_file("truck-author.json", TRUCK_AUTHOR_TEMPLATE)

    def perform_add_action(self, target, path):
        # load it just to make sure user is in the correct dir
        self.load_author_config()

        # workaround adding directories with trailing slash
        path = path[:-1] if path.endswith("/") else path

        if not os.path.exists(path):
            print("{} doesn't exist!".format(path))
            exit(1)

        filepath = target + "-config.json"
        config = self.open_or_create_json_file(filepath, {"files":[]})

        if path not in config["files"]:
            config["files"] += [path]
        else:
            print("warning: {} already exists in config".format(path))

        self.write_json_file(filepath, config)

    def perform_release_action(self, target, version=None):

        config = self.load_author_config()
        s3util = S3Util(config)

        json_s3_uri = s3util.spec_s3_uri(target)
        json_http_uri = s3util.spec_http_uri(target)

        truck_secrets_filepath = os.path.expanduser("~/.truckrc")
        truck_secrets = self.open_or_create_json_file(truck_secrets_filepath, TRUCK_SECRETS_TEMPLATE)

        # TODO - possibly fallback to env to find the keys
        if "AWS_ACCESS_KEY_ID" not in truck_secrets or "AWS_SECRET_ACCESS_KEY" not in truck_secrets:
            print("Could not find AWS access keys in config nor env")
            print("Please fill them in ~/.truckrc")
            exit(1)

        target_config_filepath = TARGET_CONFIG_FILEPATH.format(target=target)
        if not os.path.isfile(target_config_filepath):
            print("Can't find: {}".format(target_config_filepath))
            print("Please run: truck add {} path/to/stuff".format(target))
            exit(1)

        with open(target_config_filepath) as f:
            config_json = json.loads(f.read())

        staging_dir = TRUCK_TMP_DIRECTORY
        files_dir = self.prepare_staging_area(staging_dir, config_json["files"])

        truck_dep = TruckDep(version, json_http_uri)
        truck_dep.download_spec()
        spec_json = truck_dep.spec_json

        version = version or self.infer_target_version(spec_json)
        binary_path = s3util.binary_path(target, version)
        binary_http_uri = s3util.binary_http_uri(target, version)
        binary_s3_uri = s3util.binary_s3_uri(target, version)
        spec_json[version] = binary_http_uri

        spec_filename = TRUCK_SPEC_FILENAME.format(target=target)
        spec_filepath = os.path.join(TRUCK_TMP_DIRECTORY, spec_filename)
        self.write_json_file(spec_filepath, spec_json)
        print("Updated {} spec:".format(target))
        print("{} -> {}".format(version, binary_path))

        shutil.make_archive(os.path.join(staging_dir, target), 'zip', files_dir)
        archive_filepath = os.path.join(staging_dir, target + ".zip")

        print("Created {}".format(archive_filepath))
        print("Uploading to S3 ...")

        upload_command = " ".join(map(lambda i: "=".join(i), truck_secrets.items()))
        upload_command += ' aws s3 cp "{}" "{}" --acl public-read'

        os.system(upload_command.format(spec_filepath, json_s3_uri))
        os.system(upload_command.format(archive_filepath, binary_s3_uri))

        print("Done!")
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
        TruckAction.print_actions(all_actions)
        exit(1)

    selected_action[0].trigger(args[1:])


if __name__ == '__main__':
    main()

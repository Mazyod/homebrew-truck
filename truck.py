#!/usr/bin/env python
"""
Truck - a straight-forward dependency/binary manager
this file contains both the client and authoring tools.
"""
import sys
import os
import json
import urllib
import zipfile
import shutil
from distutils.version import LooseVersion


####
# Global configuration / constants
#

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
    def __init__(self, json):
        self.version = json["version"]
        self.spec_url = json["url"]
        self.binary_url = None

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
        return os.path.join(TRUCK_ROOT_DIRECTORY, self.name, self.name + ".version")

    @property
    def spec_path(self):
        return os.path.join(TRUCK_TMP_DIRECTORY, self.spec_filename)

    @property
    def binary_path(self):
        return os.path.join(TRUCK_TMP_DIRECTORY, self.binary_filename)

    @property
    def extraction_path(self):
        return os.path.join(TRUCK_ROOT_DIRECTORY, self.name)

    @property
    def is_outdated(self):
        if not os.path.isfile(self.version_filepath):
            return True

        with open(self.version_filepath) as f:
            version = f.read()

        return version != self.version

    def download_spec(self):
        url_session = urllib.FancyURLopener()
        url_session.retrieve(self.spec_url, self.spec_path)

        with open(self.spec_path) as f:
            spec_json = json.loads(f.read())

        self.binary_url = spec_json[self.version]

    def download_binary(self):
        url_session = urllib.URLopener()
        url_session.retrieve(self.binary_url, self.binary_path)


class ClientConfig:
    def __init__(self, json):
        self.deps = map(lambda dep: TruckDep(dep), json)


####
# Truck client implementation
#
# The client allows users to either sync or pull dependencies defined by the
# truck.json file.
#

class TruckClient:

    def __init__(self):
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
            )
        ]

    def load_client_config(self):
        config_filename = "truck.json"
        if not os.path.isfile(config_filename):
            print("Cannot find {} in local directory!".format(config_filename))
            exit(1)

        with open(config_filename) as f:
            client_json = json.loads(f.read())

        return ClientConfig(client_json)

    def clean_temp_folder(self):
        try:
            shutil.rmtree(TRUCK_TMP_DIRECTORY)
        except:
            pass

        os.makedirs(TRUCK_TMP_DIRECTORY)

    def download_binaries_and_specs(self, deps):
        for dep in deps:
            dep.download_spec()
            dep.download_binary()

    def extract_archives(self, deps):
        for dep in deps:
            zref = zipfile.ZipFile(dep.binary_path, 'r')
            zref.extractall(dep.extraction_path)
            zref.close()

    def pin_versions(self, deps):
        for dep in deps:
            with open(dep.version_filepath, "w+") as f:
                f.write(dep.version)

    def fetch_deps(self, deps):

        if not deps:
            print("All deps are up to date!")
            return

        print("Updating:")
        print("\n".join([dep.name for dep in deps]))

        self.clean_temp_folder()
        self.download_binaries_and_specs(deps)
        self.extract_archives(deps)
        self.pin_versions(deps)

    def perform_sync_action(self):
        truck_config = self.load_client_config()
        deps = [dep for dep in truck_config.deps if dep.is_outdated]
        self.fetch_deps(deps)

    def perform_pull_action(self):
        truck_config = self.load_client_config()
        self.fetch_deps(truck_config.deps)


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
        versions.sort(key=lambda x: LooseVersion(x))

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

    def prepare_staging_area(self, files):

        try:
            shutil.rmtree("Tmp")
        except Exception:
            pass

        os.makedirs("Tmp")
        for f in files:
            if os.path.isdir(f):
                shutil.copytree(f, "Tmp/" + os.path.basename(f))
            else:
                shutil.copyfile(f, "Tmp/" + os.path.basename(f))

        return "Tmp"


    def write_json_file(self, filepath, config):
        with open(filepath, "w+") as f:
            f.write(json.dumps(config, indent=2) + "\n")

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

        truck_secrets_filepath = os.path.expanduser("~/.truckrc")
        truck_secrets = self.open_or_create_json_file(truck_secrets_filepath, TRUCK_SECRETS_TEMPLATE)

        # TODO - possibly fallback to env to find the keys
        if not truck_secrets["AWS_ACCESS_KEY_ID"] or not truck_secrets["AWS_SECRET_ACCESS_KEY"]:
            print("Could not find AWS access keys in config nor env")
            print("Please fill them in ~/.truckrc")
            exit(1)

        target_config_filepath = TARGET_CONFIG_FILEPATH.format(target=target)
        if not os.path.isfile(target_config_filepath):
            print("Can't find: {}".format(target_config_filepath))
            print("Please run: truck add {} path/to/stuff".format(target))
            exit(1)

        spec_filepath = TRUCK_SPEC_FILENAME.format(target=target)
        spec_json = self.open_or_create_json_file(spec_filepath, {})

        version = version or self.infer_target_version(spec_json)
        binary_path = s3util.binary_path(target, version)
        binary_http_uri = s3util.binary_http_uri(target, version)
        binary_s3_uri = s3util.binary_s3_uri(target, version)
        spec_json[version] = binary_http_uri

        self.write_json_file(spec_filepath, spec_json)
        print("Updated {} spec:".format(target))
        print("{} -> {}".format(version, binary_path))

        with open(target_config_filepath) as f:
            config_json = json.loads(f.read())

        staging_dir = self.prepare_staging_area(config_json["files"])

        shutil.make_archive(target, 'zip', staging_dir)
        archive_filepath = target + ".zip"

        print("Created {}".format(archive_filepath))
        print("Uploading to S3 ...")

        json_s3_uri = s3util.spec_s3_uri(target)
        json_http_uri = s3util.spec_http_uri(target)

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

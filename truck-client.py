#!/usr/bin/env python
"""
This script represents the client for Truck (custom dependency manager)
It is very simple, so for now, we distribute it in an adhoc fashion.
"""
import sys
import os
import json
import urllib
import zipfile
import shutil

TRUCK_ROOT_DIRECTORY = "Truck"
TRUCK_TMP_DIRECTORY = os.path.join(TRUCK_ROOT_DIRECTORY, "Tmp")

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
        return os.path.join(TRUCK_ROOT_DIRECTORY, self.name + ".version")

    @property
    def spec_path(self):
        return os.path.join(TRUCK_TMP_DIRECTORY, self.spec_filename)

    @property
    def binary_path(self):
        return os.path.join(TRUCK_TMP_DIRECTORY, self.binary_filename)

    @property
    def is_outdated(self):
        if not os.path.isfile(self.version_filepath):
            return True

        with open(self.version_filepath) as f:
            version = f.read()

        return version != self.version

    def download_spec(self):
        url_session = urllib.URLopener()
        url_session.retrieve(self.spec_url, self.spec_path)

        with open(self.spec_path) as f:
            spec_json = json.loads(f.read())

        self.binary_url = spec_json[self.version]

    def download_binary(self):
        url_session = urllib.URLopener()
        url_session.retrieve(self.binary_url, self.binary_path)


class TruckConfig:
    def __init__(self, json):
        self.deps = map(lambda dep: TruckDep(dep), json)


def clean_temp_folder():
    try:
        shutil.rmtree(TRUCK_TMP_DIRECTORY)
    except:
        pass

    os.makedirs(TRUCK_TMP_DIRECTORY)

def download_binaries_and_specs(deps):
    for dep in deps:
        dep.download_spec()
        dep.download_binary()

def extract_archives(deps):
    for dep in deps:
        zref = zipfile.ZipFile(dep.binary_path, 'r')
        zref.extractall(TRUCK_ROOT_DIRECTORY)
        zref.close()

def pin_versions(deps):
    for dep in deps:
        with open(dep.version_filepath, "w+") as f:
            f.write(dep.version)

def fetch_deps(deps):
    clean_temp_folder()
    download_binaries_and_specs(deps)
    extract_archives(deps)
    pin_versions(deps)

def print_actions():
    print("sync - downloads deps if neccessary")
    print("pull - overwrite local deps with remote deps")


def main():

    config_filename = "truck.json"
    if not os.path.isfile(config_filename):
        print("Cannot find {} in local directory!".format(config_filename))
        exit(1)

    with open(config_filename) as f:
        truck_json = json.loads(f.read())

    truck_config = TruckConfig(truck_json)

    if len(sys.argv) != 2:
        print("Please choose an action:")
        print_actions()
        exit(1)

    action = sys.argv[1]

    deps = []
    if action == "sync":
        ok_deps = [dep.name for dep in truck_config.deps if not dep.is_outdated]
        if ok_deps:
            print("Up to date deps:")
            print("\n".join(ok_deps))

        deps = [dep for dep in truck_config.deps if dep.is_outdated]
    elif action == "pull":
        deps = truck_config.deps
    else:
        print("Invalid action: " + action)
        print_actions()
        exit(1)

    if not deps:
        print("All deps are up to date!")
        exit(0)

    print("Updating:")
    print("\n".join([dep.name for dep in deps]))
    fetch_deps(deps)


if __name__ == '__main__':
    main()

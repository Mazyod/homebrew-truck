# Truck :truck:
_Binary dependency management that's easy to pick-up!_

## Problem

As iOS developers using Carthage for dependcy management, we quickly hit a roadblock trying to distribute pre-built binaries with our repo. Even when trying to use Carthage binary specification, Carthage complained when the pre-built binary was a static framework.

Regardless, we wanted something simple, straight-forward, and mostly automated for our team to use.

## Enter Truck

The way Truck aims to solve this problem is by having a versions specification file somewhere in the cloud, pointing to different compressed archives, which clients can download based on their version requirements. Done.

### Publishing a Truck Dependency

Currently, Truck only supports AWS S3 as a hosting service, but you can use anything really. So, to start with truck, you need to publish something. To publish a "Target", you'll need a Truck configuration file and a Target spec file..

```zsh
% truck init # creates truck-author.json
# in truck-author.json, specify the basepath on S3 for truck to upload to (e.g. bucket-name/truck)
% truck add MyTarget some/path/
% truck add MyTarget some/file.ext
# we just authored MyTarget-spec.json with some/path/ folder and some/file.ext
% truck release MyTarget "3.2.5"
# this pushes MyTarget.json to the basepath, and the specified files as a zip to some predefined path
# MyTarget.json will contain an entry "3.2.5" pointing to the zip file location for clients to download
```

### Consuming a Truck Dependency

For clients consuming your dependencies, it is as simple as creating a `truck.json` file with the following format:

```json
[
  {
    "url": "https://s3-region.amazonaws.com/bucket-name/truck/MyTarget.json",
    "version": "3.2.5"
  }
]
```

... Then, running `truck sync`!
This will download dependencies into `Truck/Tmp`, then extract the archives into `Truck/TARGET_NAME`.


#!/bin/bash

set -e
set -x

apt-get update -y
apt-get install -y git curl wget clang llvm-dev libxml2-dev uuid-dev libssl-dev bash patch cmake tar xz-utils bzip2 gzip sed cpio pkg-config libbz2-dev zlib1g-dev

# We must upgrade CMake to >= 3.2.3 first
curl -sSL https://cmake.org/files/v3.14/cmake-3.14.5-Linux-x86_64.tar.gz | tar -xzC /opt
export PATH=/opt/cmake-3.14.5-Linux-x86_64/bin:$PATH

if [ ${ARCH} = "x86_64" ]; then
    echo "Targeting arch x86_64"
    export MACOS_NDK=/python3-macos/x86_64/cross-toolchain/target/bin

    # if we don't have the ndk, then we create it (or download it)
    if [ ! -d "$MACOS_NDK" ]; then
        echo "Preparing the MacOS x86_64 NDK"
        mkdir -p /python3-macos/x86_64
        # We move the cross-toolchain to the target arch folder
        mv /python3-macos/cross-toolchain /python3-macos/x86_64

        #echo "Downloading the MacOS NDK"
        #pushd /python3-macos/x86_64/cross-toolchain
        # Try to download from our private resource
        #wget --load-cookies /tmp/cookies.txt "https://docs.google.com/uc?export=download&confirm=$(wget --quiet --save-cookies /tmp/cookies.txt --keep-session-cookies --no-check-certificate 'https://docs.google.com/uc?export=download&id=1CwDi0nCTdzjDmS6r4MYziZiLq51fBIIZ' -O- | sed -rn 's/.*confirm=([0-9A-Za-z_]+).*/\1\n/p')&id=1CwDi0nCTdzjDmS6r4MYziZiLq51fBIIZ" -O target.tar.xz && rm -rf /tmp/cookies.txt
        #tar --no-same-owner -xf target.tar.xz        
        #popd

        # else we create the ndk
        if [ ! -d "$MACOS_NDK" ]; then
            echo "Building the MacOS NDK"
            pushd /python3-macos/x86_64/cross-toolchain
            pushd tarballs
            # Download the MacOS SDK from our private resource
            wget --load-cookies /tmp/cookies.txt "https://docs.google.com/uc?export=download&confirm=$(wget --quiet --save-cookies /tmp/cookies.txt --keep-session-cookies --no-check-certificate 'https://docs.google.com/uc?export=download&id=1ojmEgjQbI_N22s07hGlG4tlYkLFERKe8' -O- | sed -rn 's/.*confirm=([0-9A-Za-z_]+).*/\1\n/p')&id=1ojmEgjQbI_N22s07hGlG4tlYkLFERKe8" -O MacOSX11.1.sdk.tar.bz2 && rm -rf /tmp/cookies.txt
            popd
            UNATTENDED=1 ./build.sh
            popd
        fi        
    else    
        echo "MacOS NDK found"
    fi    
else
    echo "Targeting arch arm64"
fi
pushd /python3-macos/x86_64/cross-toolchain/target/bin
ls -R
popd
cd /python3-macos

./build.sh "$@"

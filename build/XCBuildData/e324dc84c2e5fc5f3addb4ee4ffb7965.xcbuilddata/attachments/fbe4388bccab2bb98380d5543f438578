#!/bin/sh
set -e

mkdir -p "$CODESIGNING_FOLDER_PATH/python/lib"
if [ "$EFFECTIVE_PLATFORM_NAME" = "-iphonesimulator" ]; then
    echo "Installing Python modules for iOS Simulator"
    PYTHON_SLICE="$PROJECT_DIR/Support/Python.xcframework/ios-arm64_x86_64-simulator"
    PACKAGES_PATH="$PROJECT_DIR/VsLoader/app_packages.iphonesimulator"
else
    echo "Installing Python modules for iOS Device"
    PYTHON_SLICE="$PROJECT_DIR/Support/Python.xcframework/ios-arm64"
    PACKAGES_PATH="$PROJECT_DIR/VsLoader/app_packages.iphoneos"
fi

rsync -au --delete "$PYTHON_SLICE/lib/" "$CODESIGNING_FOLDER_PATH/python/lib/" 
if [ -e "$PYTHON_SLICE/Python.dSYM" ]; then 
    rsync -au --delete  "$PYTHON_SLICE/Python.dSYM" "$BUILT_PRODUCTS_DIR"
fi
rsync -au --delete "$PACKAGES_PATH/" "$CODESIGNING_FOLDER_PATH/app_packages"


#!/bin/sh
set -e

install_dylib () {
    INSTALL_BASE=$1
    FULL_EXT=$2

    # The name of the extension file
    EXT=$(basename "$FULL_EXT")
    # The name and location of the module
    MODULE_PATH=$(dirname "$FULL_EXT") 
    MODULE_NAME=$(echo $EXT | cut -d "." -f 1) 
    # The location of the extension file, relative to the bundle
    RELATIVE_EXT=${FULL_EXT#$CODESIGNING_FOLDER_PATH/} 
    # The path to the extension file, relative to the install base
    PYTHON_EXT=${RELATIVE_EXT/$INSTALL_BASE/}
    # The full dotted name of the extension module, constructed from the file path.
    FULL_MODULE_NAME=$(echo $PYTHON_EXT | cut -d "." -f 1 | tr "/" "."); 
    # A bundle identifier; not actually used, but required by Xcode framework packaging
    FRAMEWORK_BUNDLE_ID=$(echo $PRODUCT_BUNDLE_IDENTIFIER.$FULL_MODULE_NAME | tr "_" "-")
    # The name of the framework folder.
    FRAMEWORK_FOLDER="Frameworks/$FULL_MODULE_NAME.framework"

    # If the framework folder doesn't exist, create it.
    if [ ! -d "$CODESIGNING_FOLDER_PATH/$FRAMEWORK_FOLDER" ]; then
        echo "Creating framework for $RELATIVE_EXT" 
        mkdir -p "$CODESIGNING_FOLDER_PATH/$FRAMEWORK_FOLDER"

        cp "$CODESIGNING_FOLDER_PATH/dylib-Info-template.plist" "$CODESIGNING_FOLDER_PATH/$FRAMEWORK_FOLDER/Info.plist"
        plutil -replace CFBundleExecutable -string "$FULL_MODULE_NAME" "$CODESIGNING_FOLDER_PATH/$FRAMEWORK_FOLDER/Info.plist"
        plutil -replace CFBundleIdentifier -string "$FRAMEWORK_BUNDLE_ID" "$CODESIGNING_FOLDER_PATH/$FRAMEWORK_FOLDER/Info.plist"
    fi
    
    echo "Installing binary for $FRAMEWORK_FOLDER/$FULL_MODULE_NAME" 
    mv "$FULL_EXT" "$CODESIGNING_FOLDER_PATH/$FRAMEWORK_FOLDER/$FULL_MODULE_NAME"
    if [ -e "$MODULE_PATH/$MODULE_NAME.xcprivacy" ];then 
        echo "Installing XCPrivacy file for $FRAMEWORK_FOLDER/$FULL_MODULE_NAME"
        XCPRIVACY_FILE="$CODESIGNING_FOLDER_PATH/$FRAMEWORK_FOLDER/PrivacyInfo.xcprivacy"
        if [ -e "$XCPRIVACY_FILE" ]; then
            rm -rf "$XCPRIVACY_FILE"
        fi
        mv "$MODULE_PATH/$MODULE_NAME.xcprivacy" "$XCPRIVACY_FILE"
    fi
    if [ -e "$FULL_EXT.dSYM" ];then 
        echo "Installing dSYM file for $FRAMEWORK_FOLDER/$FULL_MODULE_NAME"
        DSYM_FILE="$BUILT_PRODUCTS_DIR/$FULL_MODULE_NAME.dSYM"
        if [ -e "$DSYM_FILE" ]; then
            rm -rf "$DSYM_FILE"
        fi
        mv "$FULL_EXT.dSYM" "$DSYM_FILE"
        plutil -replace CFBundleIdentifier -string "$FRAMEWORK_BUNDLE_ID" "$BUILT_PRODUCTS_DIR/$FULL_MODULE_NAME.dSYM/Contents/Info.plist"
        mv "$BUILT_PRODUCTS_DIR/$FULL_MODULE_NAME.dSYM/Contents/Resources/DWARF/$EXT" "$BUILT_PRODUCTS_DIR/$FULL_MODULE_NAME.dSYM/Contents/Resources/DWARF/$FULL_MODULE_NAME"
        find "$BUILT_PRODUCTS_DIR/$FULL_MODULE_NAME.dSYM/Contents/Resources" -name "$EXT.*" | while read YML; do
            mv "$YML" "$(dirname "$YML")/$FULL_MODULE_NAME.yml"
        done
    fi
    # Create a placeholder .fwork file where the .so was
    echo "$FRAMEWORK_FOLDER/$FULL_MODULE_NAME" > ${FULL_EXT%.so}.fwork
    # Create a back reference to the .so file location in the framework
    echo "${RELATIVE_EXT%.so}.fwork" > "$CODESIGNING_FOLDER_PATH/$FRAMEWORK_FOLDER/$FULL_MODULE_NAME.origin"     
}

echo "Install standard library extension modules..."
find "$CODESIGNING_FOLDER_PATH/python/lib/python3.14/lib-dynload" -name "*.so" -not -path "*/*.so.dSYM/*" | while read FULL_EXT; do
    install_dylib python/lib/python3.14/lib-dynload/ "$FULL_EXT"
done
echo "Install app package extension modules..."
find "$CODESIGNING_FOLDER_PATH/app_packages" -name "*.so" -not -path "*/*.so.dSYM/*" | while read FULL_EXT; do
    install_dylib app_packages/ "$FULL_EXT"
done
echo "Install app extension modules..."
find "$CODESIGNING_FOLDER_PATH/app" -name "*.so" -not -path "*/*.so.dSYM/*" | while read FULL_EXT; do
    install_dylib app/ "$FULL_EXT"
done

# Clean up dylib template 
rm -f "$CODESIGNING_FOLDER_PATH/dylib-Info-template.plist"

echo "Signing frameworks as $EXPANDED_CODE_SIGN_IDENTITY_NAME ($EXPANDED_CODE_SIGN_IDENTITY)..."
find "$CODESIGNING_FOLDER_PATH/Frameworks" -name "*.framework" -exec /usr/bin/codesign --force --sign "$EXPANDED_CODE_SIGN_IDENTITY" ${OTHER_CODE_SIGN_FLAGS:-} -o runtime --timestamp=none --preserve-metadata=identifier,entitlements,flags --generate-entitlement-der "{}" \; 


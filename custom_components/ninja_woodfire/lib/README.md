# libgrillcore_android.so

Place the ARM64 native library here to enable local BLE decryption.

## How to extract

The library comes from the Ninja Pro Connect Android APK.

```bash
# Download the XAPK from apkpure.com, then:
unzip ninja.xapk "*.apk" -d ninja_extracted/
unzip ninja_extracted/config.arm64_v8a.apk \
    lib/arm64-v8a/libgrillcore_android.so \
    -d ninja_arm64/
cp ninja_arm64/lib/arm64-v8a/libgrillcore_android.so \
    custom_components/ninja_woodfire/lib/
```

## Architecture

This is an ARM64 ELF shared library (EM_AARCH64).
It runs on: Raspberry Pi 4/5, HA Yellow, HA Green, HA Blue.
It does NOT run on x86_64 (Intel/AMD).

For x86_64 development machines, the integration will log a warning
and operate in read-only mode without command support until the
protocol encryption is fully reverse-engineered.

## File

Expected filename: `libgrillcore_android.so`
Size: approximately 4.7 MB
SHA-1 of known good version: 76df31865ed3bef8ecba944a1d8aad13701ae0d1

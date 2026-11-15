const { withAndroidManifest } = require('expo/config-plugins')

/**
 * Expo config plugin that configures AndroidManifest.xml for Android TV / Google TV:
 * - Declares leanback and non-required touchscreen features
 * - Adds LEANBACK_LAUNCHER category to MainActivity so the app appears on TV launchers
 * - Sets an application banner fallback using @mipmap/ic_launcher
 */
module.exports = function withAndroidTv(config) {
  return withAndroidManifest(config, (mod) => {
    const manifest = mod.modResults.manifest

    if (!manifest['uses-feature']) {
      manifest['uses-feature'] = []
    }

    const ensureFeature = (name, required) => {
      const exists = manifest['uses-feature'].some(
        (f) => f.$ && f.$['android:name'] === name,
      )
      if (!exists) {
        manifest['uses-feature'].push({
          $: {
            'android:name': name,
            'android:required': String(required),
          },
        })
      }
    }

    ensureFeature('android.software.leanback', false)
    ensureFeature('android.hardware.touchscreen', false)

    const application = manifest.application?.[0]
    if (application) {
      if (!application.$['android:banner']) {
        application.$['android:banner'] = '@mipmap/ic_launcher'
      }

      const mainActivity = application.activity?.find(
        (act) => act.$?.['android:name'] === '.MainActivity',
      )
      if (mainActivity && Array.isArray(mainActivity['intent-filter'])) {
        const launcherFilter = mainActivity['intent-filter'].find((filter) =>
          filter.category?.some(
            (cat) => cat.$?.['android:name'] === 'android.intent.category.LAUNCHER',
          ),
        )
        if (launcherFilter) {
          const hasLeanback = launcherFilter.category?.some(
            (cat) =>
              cat.$?.['android:name'] === 'android.intent.category.LEANBACK_LAUNCHER',
          )
          if (!hasLeanback) {
            launcherFilter.category.push({
              $: { 'android:name': 'android.intent.category.LEANBACK_LAUNCHER' },
            })
          }
        }
      }
    }

    return mod
  })
}

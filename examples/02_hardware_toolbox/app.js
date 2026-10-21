App({
  onLaunch(options) {
    console.log('[HardwareToolbox] App onLaunch, from:', options ? options.fromApp : 'unknown');
  },
  onShow() {
    console.log('[HardwareToolbox] App onShow');
  },
  onHide() {
    console.log('[HardwareToolbox] App onHide');
  },
  onDestroy() {
    console.log('[HardwareToolbox] App onDestroy');
  }
});

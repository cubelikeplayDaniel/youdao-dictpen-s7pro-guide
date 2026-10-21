import brightnessModule from 'brightness';
import volumeModule from 'volume';
import batteryInfoModule from 'batteryInfo';
import wifiModule from 'wifi';
import buttonEventModule from 'buttonEvent';

Page({
  data() {
    return {
      brightnessLevel: 116,
      volumeLevel: 8,
      batteryLevel: 95,
      isCharging: false,
      wifiSignal: 4,
      tipPressed: false,
      lastEventName: '就绪'
    };
  },
  created() {
    console.log('[HardwareToolbox] Page created');
    try {
      if (brightnessModule && brightnessModule.Brightness) {
        this._brightness = new brightnessModule.Brightness();
      }
    } catch (e) {
      console.log('[Init brightness error]', e);
    }
    try {
      if (volumeModule && volumeModule.Volume) {
        this._volume = new volumeModule.Volume();
      }
    } catch (e) {
      console.log('[Init volume error]', e);
    }
    try {
      if (batteryInfoModule && batteryInfoModule.BatteryInfo) {
        this._battery = new batteryInfoModule.BatteryInfo();
      }
    } catch (e) {
      console.log('[Init battery error]', e);
    }
    try {
      if (wifiModule && wifiModule.Wifi) {
        this._wifi = new wifiModule.Wifi();
      }
    } catch (e) {
      console.log('[Init wifi error]', e);
    }
    try {
      if (buttonEventModule && buttonEventModule.ButtonEvent) {
        this._btn = new buttonEventModule.ButtonEvent();
        if (typeof this._btn.setButtonEventReady === 'function') {
          this._btn.setButtonEventReady(true);
        }
      }
    } catch (e) {
      console.log('[Init buttonEvent error]', e);
    }
  },
  pageShowing() {
    console.log('[HardwareToolbox] Page showing');
    try {
      if (this._brightness && typeof this._brightness.getBrightness === 'function') {
        const b = this._brightness.getBrightness();
        if (typeof b === 'number' && b >= 0) this.brightnessLevel = b;
      }
    } catch (e) {
      console.log('[getBrightness error]', e);
    }
    try {
      if (this._volume && typeof this._volume.getVolume === 'function') {
        const v = this._volume.getVolume();
        if (typeof v === 'number' && v >= 0) this.volumeLevel = v;
      }
    } catch (e) {
      console.log('[getVolume error]', e);
    }
    try {
      if (this._battery) {
        if (typeof this._battery.getBatteryCapacity === 'function') {
          this.batteryLevel = this._battery.getBatteryCapacity();
        }
        if (typeof this._battery.isCharging === 'function') {
          this.isCharging = this._battery.isCharging();
        }
      }
    } catch (e) {
      console.log('[getBattery error]', e);
    }
    try {
      if (this._wifi && typeof this._wifi.isOpen === 'function' && this._wifi.isOpen()) {
        if (typeof this._wifi.getWifiQual === 'function') {
          this.wifiSignal = this._wifi.getWifiQual();
        }
      }
    } catch (e) {
      console.log('[getWifi error]', e);
    }
    try {
      if (this._btn && typeof this._btn.on === 'function') {
        this._btn.on('headButtonPress', () => {
          this.tipPressed = true;
          this.lastEventName = '笔尖下压 (headButtonPress)';
        });
        this._btn.on('headButtonRelese', () => {
          this.tipPressed = false;
          this.lastEventName = '笔尖松开 (headButtonRelese)';
        });
        this._btn.on('homeButtonClick', () => {
          this.lastEventName = 'Home键单击 (homeButtonClick)';
        });
      }
    } catch (e) {
      console.log('[button listener error]', e);
    }
  },
  pageHidden() {
    console.log('[HardwareToolbox] Page hidden');
  },
  methods: {
    handleBack() {
      console.log('[HardwareToolbox] handleBack triggered, calling this.$page.finish()');
      if (this.$page && typeof this.$page.finish === 'function') {
        this.$page.finish();
      } else if (typeof $falcon !== 'undefined' && $falcon.closeApp) {
        $falcon.closeApp();
      }
    },
    changeBrightness(delta) {
      let next = Math.max(10, Math.min(255, this.brightnessLevel + delta));
      this.brightnessLevel = next;
      try {
        if (this._brightness && typeof this._brightness.setBrightness === 'function') {
          this._brightness.setBrightness(next);
        }
      } catch (e) {
        console.log('[setBrightness error]', e);
      }
    },
    changeVolume(delta) {
      let next = Math.max(0, Math.min(15, this.volumeLevel + delta));
      this.volumeLevel = next;
      try {
        if (this._volume && typeof this._volume.setVolume === 'function') {
          this._volume.setVolume(next);
        }
      } catch (e) {
        console.log('[setVolume error]', e);
      }
    }
  },
  render(h) {
    return h('div', {
      style: {
        width: '1020px',
        height: '240px',
        backgroundColor: '#121418',
        flexDirection: 'column',
        padding: '10px 16px'
      }
    }, [
      // 顶部导航栏
      h('div', {
        style: {
          width: '988px',
          height: '38px',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottomWidth: '1px',
          borderColor: '#262930',
          paddingBottom: '4px'
        }
      }, [
        h('div', {
          style: {
            width: '96px',
            height: '32px',
            backgroundColor: '#FF5722',
            borderRadius: '6px',
            justifyContent: 'center',
            alignItems: 'center'
          },
          on: { click: this.handleBack }
        }, [
          h('text', { style: { color: '#FFFFFF', fontSize: '16px', fontWeight: 'bold' } }, '❮ 返回主屏')
        ]),
        h('text', { style: { color: '#FFFFFF', fontSize: '20px', fontWeight: 'bold' } }, '有道词典笔 S7 Pro 硬件工具箱'),
        h('div', { style: { flexDirection: 'row', alignItems: 'center' } }, [
          h('text', { style: { color: '#B0BEC5', fontSize: '16px', marginRight: '16px' } },
            '电量: ' + this.batteryLevel + '% ' + (this.isCharging ? '⚡' : '')),
          h('text', { style: { color: '#4CAF50', fontSize: '16px' } }, 'Wi-Fi: ' + this.wifiSignal + '格')
        ])
      ]),

      // 核心控制与监控卡片列
      h('div', {
        style: {
          width: '988px',
          height: '165px',
          flexDirection: 'row',
          marginTop: '10px',
          justifyContent: 'space-between'
        }
      }, [
        // 亮度控制面板
        h('div', {
          style: {
            width: '312px',
            height: '155px',
            backgroundColor: '#1C1F26',
            borderRadius: '10px',
            padding: '12px',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }
        }, [
          h('div', { style: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' } }, [
            h('text', { style: { color: '#E0E0E0', fontSize: '16px', fontWeight: 'bold' } }, '屏幕亮度调节'),
            h('text', { style: { color: '#FFB74D', fontSize: '24px', fontWeight: 'bold' } }, '' + this.brightnessLevel)
          ]),
          h('text', { style: { color: '#78909C', fontSize: '13px' } }, '硬件背光范围: 10 ~ 255'),
          h('div', { style: { flexDirection: 'row', justifyContent: 'space-between' } }, [
            h('div', {
              style: { width: '135px', height: '42px', backgroundColor: '#2E3440', borderRadius: '8px', justifyContent: 'center', alignItems: 'center' },
              on: { click: () => this.changeBrightness(-25) }
            }, [h('text', { style: { color: '#ECEFF4', fontSize: '18px', fontWeight: 'bold' } }, '亮度 -25')]),
            h('div', {
              style: { width: '135px', height: '42px', backgroundColor: '#FF9800', borderRadius: '8px', justifyContent: 'center', alignItems: 'center' },
              on: { click: () => this.changeBrightness(25) }
            }, [h('text', { style: { color: '#FFFFFF', fontSize: '18px', fontWeight: 'bold' } }, '亮度 +25')])
          ])
        ]),

        // 音量控制面板
        h('div', {
          style: {
            width: '312px',
            height: '155px',
            backgroundColor: '#1C1F26',
            borderRadius: '10px',
            padding: '12px',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }
        }, [
          h('div', { style: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' } }, [
            h('text', { style: { color: '#E0E0E0', fontSize: '16px', fontWeight: 'bold' } }, '系统扬声器音量'),
            h('text', { style: { color: '#29B6F6', fontSize: '24px', fontWeight: 'bold' } }, '' + this.volumeLevel + ' / 15')
          ]),
          h('text', { style: { color: '#78909C', fontSize: '13px' } }, 'ALSA 增益等级: 0 ~ 15'),
          h('div', { style: { flexDirection: 'row', justifyContent: 'space-between' } }, [
            h('div', {
              style: { width: '135px', height: '42px', backgroundColor: '#2E3440', borderRadius: '8px', justifyContent: 'center', alignItems: 'center' },
              on: { click: () => this.changeVolume(-1) }
            }, [h('text', { style: { color: '#ECEFF4', fontSize: '18px', fontWeight: 'bold' } }, '音量 -1')]),
            h('div', {
              style: { width: '135px', height: '42px', backgroundColor: '#03A9F4', borderRadius: '8px', justifyContent: 'center', alignItems: 'center' },
              on: { click: () => this.changeVolume(1) }
            }, [h('text', { style: { color: '#FFFFFF', fontSize: '18px', fontWeight: 'bold' } }, '音量 +1')])
          ])
        ]),

        // 笔尖与传感器状态监控
        h('div', {
          style: {
            width: '324px',
            height: '155px',
            backgroundColor: '#1C1F26',
            borderRadius: '10px',
            padding: '12px',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }
        }, [
          h('div', { style: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' } }, [
            h('text', { style: { color: '#E0E0E0', fontSize: '16px', fontWeight: 'bold' } }, '笔尖光学压力微动'),
            h('div', {
              style: {
                width: '12px',
                height: '12px',
                borderRadius: '6px',
                backgroundColor: this.tipPressed ? '#4CAF50' : '#757575'
              }
            })
          ]),
          h('div', {
            style: {
              height: '38px',
              backgroundColor: this.tipPressed ? '#2E7D32' : '#263238',
              borderRadius: '6px',
              justifyContent: 'center',
              alignItems: 'center'
            }
          }, [
            h('text', { style: { color: '#FFFFFF', fontSize: '15px', fontWeight: 'bold' } },
              this.tipPressed ? '笔尖正在触压 (DOWN)' : '笔尖未触压 (IDLE)')
          ]),
          h('text', {
            style: { color: '#90A4AE', fontSize: '13px' }
          }, '最新事件: ' + this.lastEventName)
        ])
      ])
    ]);
  }
});

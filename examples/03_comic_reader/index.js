Page({
  data() {
    return {
      chapterTitle: '第一话 · 启程',
      currentPage: 1,
      totalPages: 8,
      leftPages: [
        { id: 1, src: 'assets/images/01.png', title: 'P01 · 序曲' },
        { id: 3, src: 'assets/images/03.png', title: 'P03 · 探索' },
        { id: 5, src: 'assets/images/05.png', title: 'P05 · 碰撞' },
        { id: 7, src: 'assets/images/07.png', title: 'P07 · 突破' }
      ],
      rightPages: [
        { id: 2, src: 'assets/images/02.png', title: 'P02 · 启程' },
        { id: 4, src: 'assets/images/04.png', title: 'P04 · 发现' },
        { id: 6, src: 'assets/images/06.png', title: 'P06 · 聚焦' },
        { id: 8, src: 'assets/images/08.png', title: 'P08 · 终章' }
      ]
    };
  },
  onLoad(query) {
    console.log('[ComicReader] onLoad, query:', query);
  },
  pageShowing() {
    console.log('[ComicReader] pageShowing');
  },
  pageHidden() {
    console.log('[ComicReader] pageHidden');
  },
  methods: {
    handleBack() {
      console.log('[ComicReader] handleBack called, finishing page...');
      if (this.$page && typeof this.$page.finish === 'function') {
        this.$page.finish();
      } else if (typeof $falcon !== 'undefined' && $falcon.closeApp) {
        $falcon.closeApp();
      }
    },
    selectPage(num) {
      console.log('[ComicReader] Selected page:', num);
      this.currentPage = num;
    }
  },
  render(h) {
    // 渲染单个漫画画卷卡片
    const renderCard = (p) => {
      return h('div', {
        key: 'card-' + p.id,
        style: {
          width: '484px',
          marginBottom: '16px',
          backgroundColor: '#161922',
          borderRadius: '10px',
          overflow: 'hidden',
          borderColor: this.currentPage === p.id ? '#FF9800' : '#262A36',
          borderWidth: '1px'
        },
        on: {
          click: () => this.selectPage(p.id)
        }
      }, [
        h('image', {
          attrs: {
            src: p.src,
            resize: 'cover'
          },
          style: {
            width: '484px',
            height: '320px'
          }
        }),
        h('div', {
          style: {
            width: '484px',
            height: '32px',
            backgroundColor: '#1E222D',
            flexDirection: 'row',
            justifyContent: 'space-between',
            alignItems: 'center',
            paddingLeft: '12px',
            paddingRight: '12px'
          }
        }, [
          h('text', {
            style: {
              color: '#ECEFF4',
              fontSize: '15px',
              fontWeight: 'bold'
            }
          }, p.title),
          h('text', {
            style: {
              color: '#FFB74D',
              fontSize: '13px'
            }
          }, 'HD 画卷')
        ])
      ]);
    };

    return h('div', {
      style: {
        width: '1020px',
        height: '240px',
        backgroundColor: '#0E1015',
        flexDirection: 'column'
      }
    }, [
      // 顶部悬浮毛玻璃导航条
      h('div', {
        style: {
          width: '1020px',
          height: '38px',
          backgroundColor: '#141720',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingLeft: '16px',
          paddingRight: '16px',
          borderBottomWidth: '1px',
          borderColor: '#222736'
        }
      }, [
        h('div', {
          style: {
            width: '92px',
            height: '28px',
            backgroundColor: '#E53935',
            borderRadius: '6px',
            justifyContent: 'center',
            alignItems: 'center'
          },
          on: { click: this.handleBack }
        }, [
          h('text', { style: { color: '#FFFFFF', fontSize: '15px', fontWeight: 'bold' } }, '❮ 返回主屏')
        ]),
        h('div', { style: { flexDirection: 'row', alignItems: 'center' } }, [
          h('text', { style: { color: '#FFFFFF', fontSize: '18px', fontWeight: 'bold', marginRight: '10px' } }, '画卷漫画 · ' + this.chapterTitle),
          h('text', { style: { color: '#78909C', fontSize: '14px' } }, '(当前选中: P0' + this.currentPage + ')')
        ]),
        h('text', { style: { color: '#4CAF50', fontSize: '14px' } }, '共 ' + this.totalPages + ' 页 · 双列纵向惯性瀑布流')
      ]),

      // Falcon 原生垂直滚动瀑布流容器
      h('scroller', {
        attrs: {
          'scroll-direction': 'vertical',
          'show-scrollbar': false,
          scrollable: true,
          overScroll: true,
          overFling: true
        },
        style: {
          width: '1020px',
          height: '202px',
          paddingLeft: '16px',
          paddingRight: '16px',
          paddingTop: '10px'
        }
      }, [
        h('div', {
          style: {
            width: '988px',
            flexDirection: 'row',
            justifyContent: 'space-between',
            paddingBottom: '24px'
          }
        }, [
          // 左列瀑布流
          h('div', {
            style: {
              width: '484px',
              flexDirection: 'column'
            }
          }, this.leftPages.map(p => renderCard(p))),

          // 右列瀑布流
          h('div', {
            style: {
              width: '484px',
              flexDirection: 'column'
            }
          }, this.rightPages.map(p => renderCard(p)))
        ])
      ])
    ]);
  }
});

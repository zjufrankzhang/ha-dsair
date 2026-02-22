# Daikin DS-AIR Custom Component For Home Assistant

此项目是Home Assistant平台[DS-AIR](https://www.daikin-china.com.cn/newha/products/4/19/DS-AIR/)以及[金制空气](https://www.daikin-china.com.cn/newha/products/4/19/jzkq/)自定义组件的实现

支持的网关设备型号为 DTA117B611、DTA117C611，其他网关的支持情况未知。（DTA117D611 可直接选择 DTA117C611）

# 支持设备

* 空调
* 空气传感器
* 水热交换器（HD）

# 不支持设备

* 睡眠传感器
* 晴天轮
* 转角卫士
* 金制家中用防护组件
* 显示屏(黑奢系列)

# 接入方法

## 安装

**方法一：通过 HACS 安装（推荐）**

由于本项目是基于原版的扩展分支，尚未被 HACS 官方默认收录，你需要先将其作为“自定义存储库”添加到 HACS 中。

* **快捷添加**：点击下方按钮，可直接在你的 Home Assistant 中呼出添加界面：

  [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=zjufrankzhang&repository=ha-dsair&category=integration)
  
  *(在弹出的界面确认添加后，点击右下角的 **DOWNLOAD** 进行安装)*

* **手动添加**：如果上方按钮无效，请按照以下步骤操作：
  1. 打开 Home Assistant 的 **HACS** 界面。
  2. 点击右上角的三个点 `⋮`，选择 **自定义存储库 (Custom repositories)**。
  3. 在“存储库” URL 处填写：`https://github.com/zjufrankzhang/ha-dsair`
  4. “类别”选择：**集成 (Integration)**，然后点击“添加”。
  5. 关闭弹窗，在 HACS 中搜索 `DS-AIR`，点击进入并下载安装。

**方法二：手动安装**

下载本项目的代码压缩包，将其中的 `ds_air` 目录完整解压并拷贝到你 Home Assistant 的 `/config/custom_components/` 目录下（最终路径应为 `/config/custom_components/ds_air`）。安装完成后，请重启 Home Assistant。

## 配置 
    
- 方法一：在`配置-集成-添加集成`中选择`DS-AIR`

- 方法二：首先直接点击此按钮 [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ds_air)

然后依次填入网关IP、端口号、设备型号提交即可

# HD支持信息

在最新版中，增加了HD实体的支持，目前在我的DTA117C611上工作正常。

请注意：目前HD实体没办法通过主动轮询获取温度等数据，只能在HD数据发生变化后通过回调获取数据，但经过实测不影响使用自动化/脚本等方式直接设置温度。如果需要UI调整温度但没有数据的，可以通过人工设置室外机静音状态来触发状态同步。但需要注意，必须让状态有变化并持续1s左右才可以。如果设置的值与当前机器实际状态一致，不会触发状态更新的返回包。

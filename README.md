# 澄川观测湖

采集站的上报可能重复，补录会带来新的修订。澄川观测湖把接纳的修订封成不可变存储包。交班员交付有序的固定清单，夜班在更正、退役和重开数据库后仍能凭原清单核账。

## 运行

需要 Python 3.11 标准库。在项目目录运行：

```sh
python3 -B -m unittest discover -s tests -v
python3 -B workday.py
```

工作日入口在独立临时库执行 `samples/workday.json`。它登记早班批次，确认重投结果，封存全值及两级差量，发布并核对两份交班清单，退役 P，最后重开并检查原清单及回执。手算样例用 P:0 的 `AB` 构造 Q:0 的 `Ax`，再构造 R:0 的 `Ax!`。另一份清单直接选择 P:1 的 `CD`。

## Python API

| 操作 | 入口 | 输入及结果 |
| --- | --- | --- |
| 建库和重开 | `maintenance.transactions.open_database(path)` 与 `initialize_database(db)` | 连接由调用者关闭。初始化可重跑并保留已有数据。 |
| 接纳批次 | `ingest.batches.accept_batch(db, BatchSubmission(source, batch_id, observations))` | `Observation(RevisionKey(source, record, revision), value)` 的有序序列。返回原序修订身份和本次新增数。 |
| 封存包 | `packing.seal.seal_pack(db, pack_id, selections)` | 全值用 `SealSelection(revision)`，差量用 `SealSelection(revision, PackAddress(pack_id, slot), prefix)`。返回包位序列和封存字节数。 |
| 发布快照 | `snapshot.publish.publish_snapshot(db, snapshot_id, addresses)` | 按给定地址序列返回原清单字节和发布回执。同号同序可重领。 |
| 核账 | `reading.open.read_snapshot(db, selector)` | `selector` 为快照号或保存的原始清单 `bytes`。返回逐位置的包位、修订身份、原始字节和长度。`open_snapshot` 可单独取得登记的清单结构。 |
| 退役 | `maintenance.retire.retire_pack(db, pack_id)` | 退役一个活动包，返回持久回执，含移除的封存字节数及保全的包位数。可用 `maintenance.receipts.load_retirement_receipt` 重领，`maintenance.active.list_active_packs` 核对活动包。 |

标识使用 1–128 个 ASCII 字符，首字符为字母或数字，后续可用字母、数字、点、连字符和下划线。槽号从零开始，由选择顺序分配，包号和槽号共同标识地址。修订身份包括来源号。清单与批次可保留重复位置，空序列有效，空字节是有效的观测值。值必须以 `bytes` 传入。

同一来源和批次号重投时，有序输入须与原批次完全相同。本次新增数为零。同修订同字节也可出现在新批次中。更正使用新修订号，旧修订继续可选。非法输入使用 `InvalidObservation`，已登记身份或批次发生冲突使用 `RevisionConflict`。整批接纳使用一个写事务。

差量以已经封存且当前可完整还原的基值为基础。前缀长度 p 必须满足 `0 <= p <= len(base)`，目标的前 p 个字节也须相同。包保存基址、前缀长度和目标后缀，还原逐层计算 `base[:p] + suffix`。零前缀仍需可解析的基址。选择中的未知修订、非法地址、缺失基址或无效前缀引发 `SealError`，失败的包无载荷也无活动资格。包号一经分配便保留。

发布前逐项核实包位可还原。同号异序、未知地址或不完整证据引发 `PublicationError`。读回使用一个数据库读视图，并核对固定清单的修订身份。未知快照、原清单不符、包损坏或基链不完整引发 `SnapshotReadError`，调用者只会在全部位置成功后收到结果。发布回执包含清单摘要和逐位置累计的记录数与字节数。

退役保全所有已发布清单的直接和间接依赖，移除目标包在活动库中的整份封存载荷。其他封存包及原清单字节保持原样。替代目录、替代载荷、退役标记和回执一起提交。未知或已退役的包号以及退役事务失败引发 `RetirementError`。核账以已发快照为保全边界，未被已发清单保全的包位随底层载荷退出可能失去可读性。

公开操作各自管理事务。调用时传入由 `open_database` 打开且当前没有事务的连接。同一连接由调用者顺序使用，并发会话分别打开连接。包容量按实际封存编码的长度计算，核账长度按解码所得原字节计算。所有顺序、编码和回执都由输入决定。

# 固定快照的字节贡献

澄川观测湖的封包员有时在两份内容相同的修订中选定一份作差量基底。普通快照在退役后仍能读回字节。带贡献快照还要保全实际选取的来源，以便夜班按原清单复核。

## 公开接口

- `snapshot.publish.publish_with_contributions(db, snapshot_id, addresses)` 接收与 `publish_snapshot` 相同的参数，返回 `PublicationResult`，含原始清单字节和 `PublicationReceipt`。回执沿用快照号、记录数、字节总数及该清单的 SHA-256。发布错误抛 `PublicationError`，包括提交失败。
- `reading.open.read_contributions(db, selector)` 接收快照号或与已登记清单完全相同的 `bytes`。结果提供 `snapshot_id` 和 `rows`。`rows` 为有序元组，各行提供 `position`、`address`、`revision`、`value`、`byte_length`，含义与普通核账相同。每行还提供 `contributions`，其值为按输出位置排序的区间元组。每项为 `(out_start, out_end, source_revision, source_start, source_end)` 五元组，`source_revision` 为完整 `RevisionKey`。所有区间用零基、半开字节偏移。
- `reading.open.MissingContributionEvidence` 是 `SnapshotReadError` 的子类。用合法选择器请求任一普通快照的贡献时抛此异常。未知快照、非法选择器、坏证据或带贡献快照的证据不完整均须以 `SnapshotReadError` 拒绝整次读取。

## 来源和固定承诺

原始全值的字节来自本项修订。差量的前缀继承实际封存基址的贡献，仅保留落在前缀内的部分。后缀来自差量目标修订，源偏移从目标的前缀长度算起。相同字节可有不同来源。输出区间须无空隙、无重叠地覆盖全值，每段来源长度须等于输出长度。相邻段若来源修订相同且来源区间连续，合为一段。有身份的空值对应空区间元组。清单允许空序列和重复地址，重复地址在每个原位置分别返回。

已退役的 V1 替代值保存了字节，但可能缺少来源证据。新发布如果实际继承非空的未知区间，整单失败。未知区间全部被裁去时可发布。即使前缀为零，原有基链校验也须通过。对其他首次发布，以届时能取得的真实封存证据为准。退役后的固定承诺针对退役前已成功发布的带贡献快照。

贡献、清单与回执一次生效。快照号由两种发布模式共享，任一方向混用同号均报错。同模式、同号、同一有序地址序列的重领返回首次清单及回执，异序报错。带贡献快照也可用原普通读取接口取得字节，并受原退役保全规则保护。旧快照仍可普通核账及重领。非法输入、坏证据或提交失败不留下部分发布。贡献读取须校验精确清单、各位置的地址、修订、字节及对应区间证据的完整性，成功后才一次交付。内部持久表示自定，允许全量遍历和物化。

## 样例和核验

`contribution_examples.build_chain(db, base_slot)` 在已初始化的空库中封存两份 `AB`，其修订分别为 `station/left/v1` 和 `station/right/v1`。`base_slot` 为 0 或 1，决定 Q 实际用哪份作为基底。Q 的 `Ax` 保留 1 字节，R 的 `Ax!` 保留 Q 的 2 字节，S 的 `A` 只保留 R 的首字节。函数返回 `(R:0, S:0, P:2, R:0)`，P:2 是有身份的空值。

取 `base_slot=0` 时，R 两次出现的区间都为 `[0,1) → station/left/v1[0,1)`、`[1,2) → station/ax/v1[1,2)`、`[2,3) → station/axbang/v1[2,3)`。S 只留第一段，P:2 的区间元组为空。取 `base_slot=1` 时，所有保留的首字节改归 `station/right/v1[0,1)`，字节和其余贡献相同。若以原始 `AB` 为基底，用同一修订重新封存 `AB` 并继承 1 字节，两段合成来自该修订的 `[0,2)`。

用两种基址核对手算结果。至少一次保存原清单、依次退役 P 和 Q、核对原包载荷移除、关闭连接后重开，再按原清单与快照号比较全部行，并核对同序重领及异序和跨模式冲突。

`load_v1_database(db)` 把所附 V1 SQL 数据装入尚未初始化的空库。随后运行 `initialize_database(db)` 启用当前模式。旧清单 `legacy` 能读回 `Ax`。调用 `seal_legacy_descendants(db)` 后，S:0 继承缺证的首字节，带贡献发布须拒绝。S:1、S:2 使用零前缀，分别产生 `00 7a` 与空值。S:1 的唯一贡献是 `(0, 2, RevisionKey('station', 'fresh', 'v1'), 0, 2)`，S:2 仍有行且贡献为空。破坏必要包证据或改动原清单字节的读取应整次失败。损坏零前缀的必要基链也须拒绝。

`install_publication_commit_fault(db)` 为样例库安装延迟外键触发器，使下一次插入发布回执的事务在提交时报错。验明失败后清单及回执无记录，移除 `fixture_publication_fault` 触发器，重开并以相同快照号重试。交付时说明贡献表示、冻结边界和旧证据缺失的处理。沿用 README.md 的完整原测试，并把联合核验及退役重开演示接入现有 `.pointwise-runtime.json` 的 `verify` 和 `demo`。沿用清单的版本与命令格式，核验失败返回非零，演示显示实际来源区间。

# Documentation map

| Need                                                         | Start here                                                                                                                                    |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Find a feature, its UI and tests; choose where new code goes | [Architecture and domain ownership](architecture.md)                                                                                          |
| Setup, commands, threading, boot and test groups             | [Developer guide](../DEVELOPER.md)                                                                                                            |
| Domain language                                              | [Glossary](../CONTEXT.md)                                                                                                                     |
| QML slots/signals and payload rules                          | [Bridge reference](../waves/desktop/BRIDGE.md)                                                                                                |
| Branches, issues, reviews and validation evidence            | [Implementation workflow](agents/implementation-workflow.md), [issue tracker](agents/issue-tracker.md), [triage](agents/triage-labels.md)     |
| Architecture decisions                                       | [ADRs](adr/): quality, disabled-provider queue, sidecars, Apple bundling, wrapper distribution, onboarding, My Music, capabilities, Windows   |
| Apple Music behavior and integration contract                | [Provider specification](apple-music-provider-spec.md); follow its referenced ADRs                                                            |
| Dependency changes                                           | [Update policy](dependency-updates.md)                                                                                                        |
| Packaging and platform decisions                             | [Platform review](platform-enablement-review.md), [wrapper distribution](wrapper-image.md), [license review](wrapper-image-license-review.md) |
| What a recorded build/launch actually proved                 | [Evidence index](evidence/README.md)                                                                                                          |

`research/` contains dated surveys and experiments, not current contracts.
Its file/line citations refer to the revisions named in those documents.
Review-thread dispositions likewise record source at the reviewed revision.
Use the architecture map for current paths. Local dated audit notes and logs
under `audits/` are ignored; promote durable rules into the documents above
instead of duplicating an audit narrative in product docs.

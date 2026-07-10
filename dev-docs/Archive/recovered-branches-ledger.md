# Recovered-branches ledger — 2026-07-10

During the post-OS-rebuild recovery investigation, all local branches from
the pre-rebuild working clone were pushed to GitHub and audited. Every one
was confirmed content-merged into main (or superseded); the evolved scoring
calibration turned out to live in the cartridge's training_weights.db (now
bundled as the repo baseline). The branches below were then deleted from
the remote. Their tip SHAs are recorded here; the pre-rebuild clone on the
owner's F: drive retains all objects, so any of them can be re-pushed by SHA
if ever needed.

| Branch | Tip SHA |
|---|---|
| `chore/docs-refactor` | `ab88401b66a275055da3d289a6561738323420af` |
| `chore/milestones-pr-rollup` | `9585b728d5b50f875f8f6ba0c591611208d1ad4c` |
| `claude/blissful-ritchie-3ece87` | `f8d6158f0070d47d3e232b9061ecdd7df234ea91` |
| `claude/busy-easley-9b015a` | `79ca09b344b138cbcae2c9390756abea4ee84d6a` |
| `claude/competent-shamir-f6d55c` | `3c40e5d445218349f4361ceef7f5818e9e0aba8a` |
| `claude/condescending-elgamal-46430d` | `25cb0931156b24ddc34971678577d93bd1ec8840` |
| `claude/dt-log-fixed-height` | `79e68f2ccf70557588ef20f911873e6d3aecb375` |
| `claude/dt-maroon-accent` | `79e68f2ccf70557588ef20f911873e6d3aecb375` |
| `claude/dt-panel-integrated` | `e4f5f9dadf0605b32af02150a1a4070d6a707fae` |
| `claude/dt-panel-tier1` | `8eb509cd68bf351ffcf6f3723448836f877bb5fb` |
| `claude/elated-darwin-742cb8` | `d79328abc843ebfc68b050da9478580a3b4c6b73` |
| `claude/elated-poitras-b2c9ca` | `a818a9eee3caaa50a780023fe2c4d8edee1ab99c` |
| `claude/festive-faraday-72175a` | `7041cf883ebf5effd1f46b4ba449336b71174c09` |
| `claude/fix-tag-manager` | `af23127f30dc43f56075b4dc42d35301e97d8f7f` |
| `claude/hopeful-chebyshev-577e75` | `19fddb7d3b3b3f8a4f512a29d9b922ed31394e0f` |
| `claude/infallible-sanderson-5668e6` | `f7e1a9c905b598ee427ffd81f231c2b1a215a27c` |
| `claude/interesting-ritchie-6f04c2` | `4f5aa04aaf7a9de32a397f7f1c00d1942013582a` |
| `claude/jolly-zhukovsky-2b0f94` | `a9a6f6075c0ea3621f78b6376c621700e8173f61` |
| `claude/lucid-elion-f6b3d6` | `2fd73cea062ef3d1e89628c8e9bfbde2eb396ee4` |
| `claude/priceless-shannon-504466` | `48bc9bf7e3c240113579a786f24e67ca68489c64` |
| `claude/strange-morse-81e87d` | `afd4da2dbd6b534d1e108f450a2c747c8d250968` |
| `claude/sweet-lamport-000bb9` | `24c73416e0abb546488d5669ee7836405ab9d6ad` |
| `claude/thirsty-buck-4432e7` | `6372825be4305f9f284f6507c1a5e44292f17a26` |
| `claude/thirsty-haibt-f3fb03` | `c7c4c0c7f0f4516bd461ced892f8c298148cd2c1` |
| `claude/trusting-mendel-db7975` | `7b41d23d0a6804959ac37f48473a878f838ccfd4` |
| `claude/vigorous-sinoussi-5ce2f8` | `1b49e2dd40ee3cb17bc360588f296fe4968782aa` |
| `feature/cartridge-identity` | `4e5fe777be4ed15a2af04f7e9caed96732cd7c5c` |
| `feature/cartridge-manager` | `ac6699c644441ec10ed8005b620b431fd57f9630` |
| `feature/cartridge-manager-preview-tab` | `08469e2902c7836b91923129327eda752a909c3b` |
| `feature/gui-layer` | `ab88401b66a275055da3d289a6561738323420af` |
| `fix/remove-dead-nima` | `13726639c95380260651c84937f9b2f834dadc56` |
| `pipeline-v2-and-fixes` | `9e38194b53fa1e27dfdec7f0c82e039bfa5ea55f` |
| `recovery/cartridge-db-evidence` | `c7541dc42a70a087dac003a2be89fc4d20129825` |
| `recovery/local-rebuild-2026-07` | `9585b728d5b50f875f8f6ba0c591611208d1ad4c` |
| `recovery/merge-local-rebuild` | `9e79da945064531389743e5ca3c36423b17a97f0` |
| `worktree-agent-a149eca3f3403904d` | `48bc9bf7e3c240113579a786f24e67ca68489c64` |
| `worktree-agent-a9e4f9e5e02ff1184` | `48bc9bf7e3c240113579a786f24e67ca68489c64` |
| `worktree-agent-acb896d15915d4e81` | `48bc9bf7e3c240113579a786f24e67ca68489c64` |

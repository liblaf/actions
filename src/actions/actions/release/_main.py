import githubkit

import actions
import actions.toolkit.github as g
from actions.toolkit import core
from actions.utils import cksum

from ._inputs import Inputs


@actions.utils.action()
async def main(inputs: Inputs) -> None:
    gh: g.GitHub = g.GitHub(githubkit.ActionAuthStrategy())
    repo: g.RepoClient = gh.repo(*inputs.repo.split("/"))
    create: bool = False
    cksums_local: dict[str, str] = cksum.hash_files(*inputs.files, hasher=inputs.hasher)
    if await repo.release_exists(inputs.tag):
        cksums_remote: dict[str, str] = await repo.release_cksums(
            inputs.tag, inputs.hasher
        )
        if cksums_local == cksums_remote:
            core.notice(f"Hashsums match, skip release: {inputs.tag!r}")
            return
        if inputs.clobber:
            await repo.release_delete(inputs.tag)
            create = True
            core.notice(f"Recreate release: {inputs.tag!r}")
        else:
            core.notice(f"Update release: {inputs.tag!r}")
            await repo.release_upload(inputs.tag, *inputs.files, hasher=inputs.hasher)
    else:
        create = True
        core.notice(f"Create release: {inputs.tag!r}")
    if create:
        await repo.release_create(
            inputs.tag,
            *inputs.files,
            hasher=inputs.hasher,
            notes=inputs.changelog,
            prerelease=inputs.prerelease,
        )

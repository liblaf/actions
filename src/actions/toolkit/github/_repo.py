import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import githubkit
import githubkit.exception
import githubkit.typing
import githubkit.versions.latest.models as m
import httpx
import tenacity

from actions.typing import StrPath
from actions.utils import cksum

if TYPE_CHECKING:
    from collections.abc import Coroutine


class RepoClient:
    _gh: githubkit.GitHub
    owner: str
    repo: str

    def __init__(self, gh: githubkit.GitHub, owner: str, repo: str) -> None:
        self._gh = gh
        self.owner = owner
        self.repo = repo

    async def release_get(self, tag: str) -> m.Release:
        resp: githubkit.Response[
            m.Release
        ] = await self._gh.rest.repos.async_get_release_by_tag(
            self.owner, self.repo, tag
        )
        return resp.parsed_data

    async def release_exists(self, tag: str) -> bool:
        try:
            _release = await self.release_get(tag)
        except githubkit.exception.RequestFailed as err:
            if err.response.status_code == httpx.codes.NOT_FOUND:
                return False
            raise
        else:
            return True

    async def release_create(
        self,
        tag: str,
        *files: StrPath,
        hasher: str | None = None,
        notes: str | None = None,
        prerelease: bool = False,
    ) -> m.Release:
        resp: githubkit.Response[
            m.Release
        ] = await self._gh.rest.repos.async_create_release(
            self.owner,
            self.repo,
            tag_name=tag,
            name=tag,
            body=notes,
            prerelease=prerelease,
            generate_release_notes=not notes,
        )
        release: m.Release = resp.parsed_data
        await self.release_upload(tag, *files, hasher=hasher)
        return release

    async def release_delete(self, tag: str) -> None:
        release: m.Release = await self.release_get(tag)
        await self._gh.rest.repos.async_delete_release(
            self.owner, self.repo, release.id
        )
        # workaround for [cli/cli#5024 (comment)](https://github.com/cli/cli/issues/5024#issuecomment-1028018586)
        await self._wait_until_release(tag, exists=False)

    async def release_download(self, tag: str, asset_name: str) -> bytes:
        resp: httpx.Response = await self._gh._arequest(  # noqa: SLF001
            "GET",
            f"https://github.com/{self.owner}/{self.repo}/releases/download/{tag}/{asset_name}",
        )
        resp = resp.raise_for_status()
        return resp.content

    async def release_delete_asset(self, tag: str, asset_name: str) -> None:
        release: m.Release = await self.release_get(tag)
        for asset in release.assets:
            if asset.name == asset_name:
                await self._gh.rest.repos.async_delete_release_asset(
                    self.owner, self.repo, asset.id
                )
                return

    async def release_cksums(self, tag: str, hasher: str) -> dict[str, str]:
        try:
            data: bytes = await self.release_download(tag, cksum.filename.sums(hasher))
        except httpx.HTTPStatusError as err:
            if err.response.status_code == httpx.codes.NOT_FOUND:
                return {}
            raise
        else:
            return cksum.parse(data)

    async def release_upload(
        self, tag: str, *files: StrPath, hasher: str | None = None
    ) -> list[m.ReleaseAsset]:
        cksums: dict[str, str]
        if hasher:
            cksums = await self.release_cksums(tag, hasher)
        else:
            cksums = {}
        futures: list[Coroutine[Any, Any, m.ReleaseAsset]] = []
        for file in files:
            fpath: Path = Path(file)
            data: bytes = fpath.read_bytes()
            futures.append(self._release_upload_asset(tag, fpath.name, data=data))
            if hasher:
                s: str = cksum.hash_bytes(data, hasher)
                cksums[fpath.name] = s
                futures.append(
                    self._release_upload_asset(
                        tag,
                        cksum.filename.single(fpath, hasher),
                        data=cksum.dumps({fpath.name: s}).encode(),
                    )
                )
        if hasher:
            futures.append(
                self._release_upload_asset(
                    tag,
                    cksum.filename.sums(hasher),
                    data=cksum.dumps(cksums).encode(),
                )
            )
        return await asyncio.gather(*futures)

    @tenacity.retry(
        wait=tenacity.wait_random_exponential(),
        retry=tenacity.retry_if_exception_type(tenacity.TryAgain),
    )
    async def _wait_until_release(self, tag: str, *, exists: bool) -> None:
        if await self.release_exists(tag) != exists:
            raise tenacity.TryAgain

    async def _release_upload_asset(
        self, tag: str, name: str, *, data: bytes
    ) -> m.ReleaseAsset:
        release: m.Release = await self.release_get(tag)
        await self.release_delete_asset(tag, name)
        # TODO: replace with `async_upload_release_asset()` until [yanyongyu/githubkit#150](https://github.com/yanyongyu/githubkit/issues/150) is fixed
        resp: httpx.Response = await self._gh._arequest(  # noqa: SLF001
            "POST",
            f"https://uploads.github.com/repos/{self.owner}/{self.repo}/releases/{release.id}/assets",
            params={"name": name},
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        return m.ReleaseAsset.model_validate(resp.json())

import asyncio
from zoneinfo import ZoneInfo
import json
import os
from datetime import datetime

from atproto import AsyncClient, AtUri, models

from trollsavar.image import draw_red_cross

LIMIT = 100


async def create_list(client: AsyncClient, name: str, description: str, avatar):
    response = await client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client.me.did,
            collection="app.bsky.graph.list",
            record={
                "$type": "app.bsky.graph.list",
                "name": name,
                "purpose": "app.bsky.graph.defs#modlist",
                "description": description,
                "avatar": avatar.blob,
                "createdAt": client.get_current_time_iso(),
            },
        )
    )
    print("List created:", response.uri)
    return response.uri


async def add_user_to_list(client, user_did, list_uri):
    result = await client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client.me.did,
            collection="app.bsky.graph.listitem",
            record={
                "$type": "app.bsky.graph.listitem",
                "subject": user_did,
                "list": list_uri,
                "createdAt": client.get_current_time_iso(),
            },
        )
    )

    print("User added to list:", user_did)
    return result.uri


async def remove_user_from_list(client: AsyncClient, list_item_uri):
    # FIXME: this method is not working for some reason
    at_uri = AtUri.from_str(list_item_uri)
    # print(at_uri.collection, at_uri.host, at_uri.rkey)

    await client.com.atproto.repo.delete_record(
        models.ComAtprotoRepoDeleteRecord.Data(
            collection=at_uri.collection,
            repo=at_uri.host,
            rkey=at_uri.rkey,
        )
    )
    print("User removed from list:", list_item_uri)


async def delete_list(client: AsyncClient, list_item):
    at_uri = AtUri.from_str(list_item.uri)
    await client.com.atproto.repo.delete_record(
        {
            "repo": client.me.did,
            "collection": "app.bsky.graph.list",
            "rkey": at_uri.rkey,
        }
    )
    print("List deleted:", list_item.uri)


async def delete_lists(client: AsyncClient, lists_to_delete):
    for item in lists_to_delete:
        await delete_list(client, item)


async def get_users_to_blacklist(client: AsyncClient, actor):
    blacklist = set()
    data = await client.get_followers(actor=actor.did, limit=LIMIT)
    while True:
        for follower in data.followers:
            if follower.did in blacklist:
                break
            blacklist.add(follower.did)
        else:
            data = await client.get_followers(
                actor=actor.did, cursor=data.cursor, limit=LIMIT
            )
            continue
        break
    blacklist.add(actor.did)
    return blacklist


def get_description(name, follower_count):
    return f"""{name} ve takipçileri. Sağ üstten "Abone ol" diyerek listedeki herkesi sessize alabilir veya engelleyebilirsiniz. Liste her 24 saatte bir güncellenir.

Kod: https://github.com/sahinakkaya/trollsavar/
Son güncelleme: {datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%Y-%m-%d %H:%M")}
Listedeki kişi sayısı: {follower_count}"""


async def create_or_get_blacklist_for_actor(
    client: AsyncClient, actor_profile, list_name, existing_lists
):
    if list_name is None:
        list_name = f"{actor_profile.display_name} ve Avaneleri"
    for item in existing_lists:
        if item.name == list_name:
            print("List already exists:", item.uri)
            list_uri = item.uri
            break
    else:
        avatar_url = actor_profile.avatar
        avatar_img = draw_red_cross(avatar_url)
        avatar = await client.upload_blob(avatar_img)
        description = f"""{actor_profile.display_name} ve takipçileri. Sağ üstten "Abone ol" tuşuna basarak listedeki herkesi sessize alabilir veya engelleyebilirsiniz. Liste her 24 saatte bir otomatik olarak güncellenir.

Bu listeyi oluşturan kodu github'da bulabilirsiniz: https://github.com/sahinakkaya/trollsavar/
    """
        list_uri = await create_list(client, list_name, description, avatar)
        print("List created:", list_uri)
    print(list_name)
    return list_uri




async def update_list_metadata(client: AsyncClient, list_uri, description):
    at_uri = AtUri.from_str(list_uri)
    list_info = await client.com.atproto.repo.get_record(
        models.ComAtprotoRepoGetRecord.Params(
            repo=at_uri.host,
            collection=at_uri.collection,
            rkey=at_uri.rkey,
        )
    )
    description = description.replace("https://github.com/sahinakkaya/trollsavar/", "github.com/sahinakkaya/...")

    list_info.value.description = description
    await client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=client.me.did,
            collection=at_uri.collection,
            rkey=at_uri.rkey,
            record=list_info.value,
        )
    )


async def update_list(client: AsyncClient, actor_profile, list_uri):
    current_dids = await get_users_to_blacklist(client, actor_profile)
    file_name = f"blacklists/{actor_profile.did}"
    if os.path.exists(file_name):
        with open(file_name, "r") as f:
            old_list = json.load(f)
    else:
        old_list = {}
    old_dids = set(old_list)
    new_users_to_blacklist = current_dids - old_dids
    print("Updated list:", new_users_to_blacklist)
    list_item_uris = old_list.copy()
    if not new_users_to_blacklist:
        print("No new users to add.")
    for did in new_users_to_blacklist:
        list_item_uris[did] = await add_user_to_list(client, did, list_uri)

    # TODO: we should remove the users from blacklist who are not following the actor anymore.
    # but the following doesn't work for some reason
    whitelist = old_dids - current_dids
    print("White list:", whitelist)
    if whitelist:
        print("Removing users from list:", whitelist)
    for did in whitelist:
        await remove_user_from_list(
            client, list_item_uris[did]
        )  # <- this is the problematic part. feel free to open a pr if you know the solution
        del list_item_uris[did]

    await remove_user_from_list(client, list_item_uris[actor_profile.did])
    await add_user_to_list(client, actor_profile.did, list_uri)
    description = get_description(actor_profile.display_name, len(list_item_uris))
    await update_list_metadata(client, list_uri, description)

    with open(file_name, "w") as f:
        json.dump(list_item_uris, f)


async def block_mod_list(client: AsyncClient, list_uri):
    await client.app.bsky.graph.listblock.create(
        repo=client.me.did,
        record=models.AppBskyGraphListblock.Record(
            subject=list_uri,
            created_at=client.get_current_time_iso(),
        ),
    )


async def unblock_mod_list(client: AsyncClient, list_uri):
    list_info = await client.app.bsky.graph.get_list(
        models.AppBskyGraphGetList.Params(list=list_uri, limit=1)
    )
    blocked = list_info.list.viewer and list_info.list.viewer.blocked
    print("Blocked:", blocked)
    if blocked:
        at_uri = AtUri.from_str(blocked)
        await client.app.bsky.graph.listblock.delete(
            client.me.did, at_uri.rkey
        )
        print("Unblocked:", blocked)

async def main():
    client = AsyncClient()
    username = os.environ["USERNAME"]
    password = os.environ["PASSWORD"]
    await client.login(username, password)

    old_lists_data = await client.app.bsky.graph.get_lists(
        models.AppBskyGraphGetLists.Params(actor=username)
    )
    actors_to_blacklist = {
        "misvakcaps.bsky.social": {"name": "M*svak Caps Trolleri"},  # you can set custom list name or...
        "furkancerkesx.bsky.social": {"name": None},  # leave it as None so it will be generated as "... ve Avaneleri"
        "abdquil.bsky.social": {"name": "Abdullah Kilim (@abdquil) ve Avaneleri"}
    }
    # for actor in actors_to_blacklist:
    #     profile = await client.get_profile(actor)
    #     print(profile.did, profile.display_name)


    # unblock all lists first, update them and then block them again. blocking and unblocking would
    # be unncessary if I didn't want to have them blocked in my personal account. but I don't want
    # see them, so I have to unblock the lists in order to get all the followers

    for actor, value in actors_to_blacklist.items():
        list_name = value["name"]
        actor_profile = await client.get_profile(actor)
        list_uri = await create_or_get_blacklist_for_actor(
            client, actor_profile, list_name, old_lists_data.lists
        )
        actors_to_blacklist[actor]["list_uri"] = list_uri
        actors_to_blacklist[actor]["actor_profile"] = actor_profile
        await unblock_mod_list(client, list_uri)

    await asyncio.sleep(5)

    # then we update the lists with the followers
    for actor, value in actors_to_blacklist.items():
        actor_profile = value["actor_profile"]
        list_uri = value["list_uri"]
        await update_list(client, actor_profile, list_uri)

    for actor, value in actors_to_blacklist.items():
        list_uri = value["list_uri"]
        await block_mod_list(client, list_uri)

    # Delete old lists
    # await delete_lists(client, old_lists_data.lists)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

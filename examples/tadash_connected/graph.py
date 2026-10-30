"""Persist measured cycles as Graphiti episodes in a local Kuzu database."""
import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import NAMESPACE_URL, uuid5

from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.edges import NextEpisodeEdge
from graphiti_core.nodes import EpisodeType, EpisodicNode

GROUP = "tadash_six"


def record_id(key):
    return str(uuid5(NAMESPACE_URL, "urn:tadash:connected:v1:" + key))


class DurableKuzuDriver(KuzuDriver):
    """Close native query results while their connection is still alive."""

    async def execute_query(self, cypher_query_, **kwargs):
        # Kuzu async futures can retain the last QueryResult past DB.close().
        # Graphiti's pinned adapter materializes rows but leaves results for GC.
        params = {k: v for k, v in kwargs.items() if v is not None and k not in ("routing_", "database_")}
        result = await self.client.execute(cypher_query_, parameters=params)
        multiple = isinstance(result, list)
        with ExitStack() as stack:
            results = [stack.enter_context(r) for r in (result if multiple else [result])]
            rows = [list(r.rows_as_dict()) for r in results]
        return (rows if multiple else rows[0]), None, None


@contextmanager
def local_graph(path):
    driver = DurableKuzuDriver(str(path))
    try:
        yield driver
    finally:
        # Graphiti's KuzuDriver.close is a no-op in the pinned release.
        driver.client.close()
        driver.db.close()


async def recall(path, catalog):
    recovered = []
    with local_graph(path) as driver:
        for uid in catalog["ids"]:
            node = await EpisodicNode.get_by_uuid(driver, uid)
            recovered.append(json.loads(node.content))
        for uid, before, after in catalog["edges"]:
            edge = await NextEpisodeEdge.get_by_uuid(driver, uid)
            if (edge.source_node_uuid, edge.target_node_uuid) != (before, after):
                raise RuntimeError("Recovered graph edge disagrees with execution order")
    return recovered


async def store_and_recall(directory, rows):
    dbpath = directory / "episodes.kuzu"
    if dbpath.exists():
        raise FileExistsError(dbpath)
    ids, edges, previous = [], [], {}
    with local_graph(dbpath) as driver:
        for row in rows:
            key = row["event_id"]
            uid = record_id(key)
            when = datetime.fromisoformat(row["at_utc"])
            node = EpisodicNode(uuid=uid, group_id=GROUP, name=key, source=EpisodeType.json,
                source_description="Tadash executed native, GMR/Mink and MyoSuite cycle",
                created_at=when, valid_at=when, content=json.dumps(row, sort_keys=True, allow_nan=False))
            await node.save(driver)
            if row["case"] in previous:
                predecessor = previous[row["case"]]
                edge = NextEpisodeEdge(uuid=record_id(predecessor + "/" + uid),
                    source_node_uuid=predecessor, target_node_uuid=uid, group_id=GROUP, created_at=when)
                await edge.save(driver)
                edges.append((edge.uuid, predecessor, uid))
            previous[row["case"]] = uid
            ids.append(uid)
        await driver.execute_query("CHECKPOINT")

    # Copy only the checkpointed database. The fresh interpreter receives IDs
    # and expected edge endpoints, never the episode contents or a sidecar WAL.
    with tempfile.TemporaryDirectory(prefix="tadash-cold-graph-") as tmp:
        snapshot = Path(tmp) / "episodes.kuzu"
        shutil.copyfile(dbpath, snapshot)
        result = subprocess.run([sys.executable, "-m", "examples.tadash_connected.graph", snapshot],
            cwd=Path(__file__).resolve().parents[2], input=json.dumps({"ids": ids, "edges": edges}),
            stdout=subprocess.PIPE, text=True, check=True)
        recovered = json.loads(result.stdout)
    if recovered != rows:
        raise RuntimeError("Recovered graph episodes disagree with executed measurements")
    return recovered, {"episodes": len(ids), "temporal_edges": len(edges), "database_reopened": True,
                       "separate_process": True, "standalone_database": True, "group": GROUP}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(recall(Path(sys.argv[1]), json.load(sys.stdin))), allow_nan=False))

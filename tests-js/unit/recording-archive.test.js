import assert from "node:assert/strict";
import test from "node:test";
import { TextDecoder } from "node:util";

import { createRecordingArchive, recordingArchiveFilename } from "../../frontend/js/runner/recording-archive.js";

const decoder = new TextDecoder();

function archiveEntries(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const endOffset = bytes.length - 22;
  assert.equal(view.getUint32(endOffset, true), 0x06054b50);
  const count = view.getUint16(endOffset + 10, true);
  let offset = view.getUint32(endOffset + 16, true);
  const entries = [];
  for (let index = 0; index < count; index += 1) {
    assert.equal(view.getUint32(offset, true), 0x02014b50);
    const crc = view.getUint32(offset + 16, true);
    const size = view.getUint32(offset + 24, true);
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localOffset = view.getUint32(offset + 42, true);
    const name = decoder.decode(bytes.subarray(offset + 46, offset + 46 + nameLength));
    assert.equal(view.getUint32(localOffset, true), 0x04034b50);
    const localNameLength = view.getUint16(localOffset + 26, true);
    const localExtraLength = view.getUint16(localOffset + 28, true);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    entries.push({ name, crc, data: bytes.slice(dataOffset, dataOffset + size) });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

test("recording archive keeps every original audio file with a stable task name", async () => {
  const archive = await createRecordingArchive([
    { task: 1, question: 2, type: "audio/webm", blob: new Blob(["hello"]) },
    { task: 2, question: null, type: "audio/mp4", blob: new Blob(["world"]) },
  ], { modifiedAt: new Date("2026-09-10T12:34:56Z") });

  assert.equal(archive.type, "application/zip");
  const entries = archiveEntries(new Uint8Array(await archive.arrayBuffer()));
  assert.deepEqual(entries.map(entry => entry.name), ["zadanie-1-vopros-2.webm", "zadanie-2.m4a"]);
  assert.deepEqual(entries.map(entry => decoder.decode(entry.data)), ["hello", "world"]);
  assert.deepEqual(entries.map(entry => entry.crc), [0x3610a686, 0x3a771143]);
});

test("recording archive filename uses the user's local calendar date", () => {
  const localDate = {
    getFullYear: () => 2026,
    getMonth: () => 8,
    getDate: () => 11,
    toISOString: () => "2026-09-10T21:30:00.000Z",
  };

  assert.equal(recordingArchiveFilename(localDate), "ege-chinese-recordings-2026-09-11.zip");
});

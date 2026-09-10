const encoder = new TextEncoder();

const crcTable = (() => {
  const table = new Uint32Array(256);
  for (let value = 0; value < table.length; value += 1) {
    let crc = value;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    table[value] = crc >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = (crc >>> 8) ^ crcTable[(crc ^ byte) & 0xff];
  return (crc ^ 0xffffffff) >>> 0;
}

function zipDateTime(value) {
  const date = value instanceof Date && !Number.isNaN(value.getTime()) ? value : new Date();
  const year = Math.max(1980, Math.min(2107, date.getFullYear()));
  return {
    date: ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
    time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2),
  };
}

function recordingFilename(recording, index) {
  const extension = recording.type?.includes("mp4") ? "m4a" : "webm";
  if (recording.task === 1 && Number.isInteger(recording.question)) {
    return `zadanie-1-vopros-${recording.question}.${extension}`;
  }
  if (Number.isInteger(recording.task)) return `zadanie-${recording.task}.${extension}`;
  return `zapis-${index + 1}.${extension}`;
}

function localHeader(entry) {
  const header = new Uint8Array(30 + entry.name.length);
  const view = new DataView(header.buffer);
  view.setUint32(0, 0x04034b50, true);
  view.setUint16(4, 20, true);
  view.setUint16(8, 0, true);
  view.setUint16(10, entry.time, true);
  view.setUint16(12, entry.date, true);
  view.setUint32(14, entry.crc, true);
  view.setUint32(18, entry.data.length, true);
  view.setUint32(22, entry.data.length, true);
  view.setUint16(26, entry.name.length, true);
  header.set(entry.name, 30);
  return header;
}

function centralHeader(entry) {
  const header = new Uint8Array(46 + entry.name.length);
  const view = new DataView(header.buffer);
  view.setUint32(0, 0x02014b50, true);
  view.setUint16(4, 20, true);
  view.setUint16(6, 20, true);
  view.setUint16(10, 0, true);
  view.setUint16(12, entry.time, true);
  view.setUint16(14, entry.date, true);
  view.setUint32(16, entry.crc, true);
  view.setUint32(20, entry.data.length, true);
  view.setUint32(24, entry.data.length, true);
  view.setUint16(28, entry.name.length, true);
  view.setUint32(42, entry.offset, true);
  header.set(entry.name, 46);
  return header;
}

function endRecord(entryCount, centralSize, centralOffset) {
  const record = new Uint8Array(22);
  const view = new DataView(record.buffer);
  view.setUint32(0, 0x06054b50, true);
  view.setUint16(8, entryCount, true);
  view.setUint16(10, entryCount, true);
  view.setUint32(12, centralSize, true);
  view.setUint32(16, centralOffset, true);
  return record;
}

export function recordingArchiveFilename(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `ege-chinese-recordings-${year}-${month}-${day}.zip`;
}

export async function createRecordingArchive(recordings, { modifiedAt = new Date() } = {}) {
  const timestamp = zipDateTime(modifiedAt);
  const entries = await Promise.all(recordings.map(async (recording, index) => {
    const data = new Uint8Array(await recording.blob.arrayBuffer());
    return {
      ...timestamp,
      crc: crc32(data),
      data,
      name: encoder.encode(recordingFilename(recording, index)),
      offset: 0,
    };
  }));
  const localParts = [];
  let localSize = 0;
  for (const entry of entries) {
    entry.offset = localSize;
    const header = localHeader(entry);
    localParts.push(header, entry.data);
    localSize += header.length + entry.data.length;
  }
  const centralParts = entries.map(centralHeader);
  const centralSize = centralParts.reduce((total, part) => total + part.length, 0);
  return new Blob([...localParts, ...centralParts, endRecord(entries.length, centralSize, localSize)], {
    type: "application/zip",
  });
}

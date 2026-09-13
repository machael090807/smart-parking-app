const fs = require("fs");
const path = require("path");

/* =========================================================
   Smart Parking API v1.1.2

   一般載入：
   - 新北：parking-newtaipei.json 快照
   - 台北：parking-taipei.json 快照
   - 不連政府即時 API

   refresh=1：
   - 才向新北市政府取得最新狀態
   - 以 cellid / id 對應既有快照
   - 保留快照座標，只更新狀態相關欄位
========================================================= */

const NTPC_DATASET_ID =
  "54A507C4-C038-41B5-BF60-BBECB9D052C6";

const NTPC_CSV_URL =
  `https://data.ntpc.gov.tw/api/datasets/${NTPC_DATASET_ID}/csv/file`;

const DEFAULT_LIMIT = 5000;
const MAX_LIMIT = 8000;

/* =========================================================
   記憶體快取
========================================================= */

let newTaipeiSnapshotCache = null;
let newTaipeiSnapshotPromise = null;

let taipeiSnapshotCache = null;
let taipeiSnapshotPromise = null;

/* =========================================================
   基本工具
========================================================= */

function clean(value) {
  if (
    value === undefined ||
    value === null
  ) {
    return "";
  }

  return String(value).trim();
}

function getValue(row, ...keys) {
  if (!row) {
    return "";
  }

  const lowerMap = {};

  for (
    const [key, value]
    of Object.entries(row)
  ) {
    lowerMap[
      String(key).toLowerCase()
    ] = value;
  }

  for (const key of keys) {
    if (
      Object.prototype.hasOwnProperty.call(
        row,
        key
      ) &&
      row[key] !== undefined &&
      row[key] !== null &&
      String(row[key]).trim() !== ""
    ) {
      return row[key];
    }

    const lowerKey =
      String(key).toLowerCase();

    if (
      Object.prototype.hasOwnProperty.call(
        lowerMap,
        lowerKey
      ) &&
      lowerMap[lowerKey] !== undefined &&
      lowerMap[lowerKey] !== null &&
      String(
        lowerMap[lowerKey]
      ).trim() !== ""
    ) {
      return lowerMap[lowerKey];
    }
  }

  return "";
}

/* =========================================================
   CSV Parser
========================================================= */

function parseCSV(text) {
  text =
    String(text || "")
      .replace(/^\uFEFF/, "");

  const rows = [];

  let row = [];
  let field = "";
  let inQuotes = false;

  for (
    let i = 0;
    i < text.length;
    i += 1
  ) {
    const char =
      text[i];

    const next =
      text[i + 1];

    if (char === '"') {
      if (
        inQuotes &&
        next === '"'
      ) {
        field += '"';
        i += 1;
      } else {
        inQuotes =
          !inQuotes;
      }

      continue;
    }

    if (
      char === "," &&
      !inQuotes
    ) {
      row.push(field);
      field = "";
      continue;
    }

    if (
      (
        char === "\n" ||
        char === "\r"
      ) &&
      !inQuotes
    ) {
      if (
        char === "\r" &&
        next === "\n"
      ) {
        i += 1;
      }

      row.push(field);
      field = "";

      if (
        row.some(
          (value) =>
            String(value).trim()
        )
      ) {
        rows.push(row);
      }

      row = [];
      continue;
    }

    field += char;
  }

  if (
    field.length ||
    row.length
  ) {
    row.push(field);

    if (
      row.some(
        (value) =>
          String(value).trim()
      )
    ) {
      rows.push(row);
    }
  }

  if (!rows.length) {
    return [];
  }

  const headers =
    rows[0].map(clean);

  return rows
    .slice(1)
    .map((values) => {
      const output = {};

      headers.forEach(
        (header, index) => {
          output[header] =
            values[index] ?? "";
        }
      );

      return output;
    });
}

/* =========================================================
   狀態
========================================================= */

function detectStatus(record) {
  if (
    record.city === "Taipei"
  ) {
    return "unknown";
  }

  const parkingStatus =
    clean(
      record.parkingstatus
    ).toLowerCase();

  const cellStatus =
    clean(
      record.cellstatus
    ).toLowerCase();

  if (
    [
      "0",
      "empty",
      "available",
      "free",
      "false"
    ].includes(parkingStatus)
  ) {
    return "empty";
  }

  if (
    [
      "1",
      "occupied",
      "used",
      "full",
      "true"
    ].includes(parkingStatus)
  ) {
    return "occupied";
  }

  const combined =
    `${parkingStatus} ${cellStatus}`;

  if (
    /空車|空位|可停|無車|available|empty|free/
      .test(combined)
  ) {
    return "empty";
  }

  if (
    /有車|已停|占用|佔用|occupied|used|full/
      .test(combined)
  ) {
    return "occupied";
  }

  return "unknown";
}

function detectSpecialType(record) {
  const text = [
    record.name,
    record.memo,
    record.roadname
  ]
    .map(clean)
    .join(" ");

  if (
    /身心障礙|身障|殘障/
      .test(text)
  ) {
    return "disabled";
  }

  if (
    /貨車|裝卸|卸貨/
      .test(text)
  ) {
    return "loading";
  }

  if (
    /婦幼|親子|孕婦/
      .test(text)
  ) {
    return "family";
  }

  return "normal";
}

function specialLabel(key) {
  switch (key) {
    case "disabled":
      return "身障車格";

    case "loading":
      return "貨車／裝卸車格";

    case "family":
      return "婦幼／親子車格";

    default:
      return "一般車格";
  }
}

function statusLabel(key) {
  switch (key) {
    case "empty":
      return "空車格";

    case "occupied":
      return "已有停車";

    default:
      return "狀態未知";
  }
}

function enrichRecord(record) {
  const normalized = {
    id:
      clean(record.id),

    cellid:
      clean(record.cellid),

    name:
      clean(record.name),

    day:
      clean(record.day),

    hour:
      clean(record.hour),

    pay:
      clean(record.pay),

    paycash:
      clean(record.paycash),

    memo:
      clean(record.memo),

    roadid:
      clean(record.roadid),

    roadname:
      clean(record.roadname),

    cellstatus:
      clean(record.cellstatus),

    isnowcash:
      clean(record.isnowcash),

    parkingstatus:
      clean(record.parkingstatus),

    latitude:
      Number(record.latitude),

    longitude:
      Number(record.longitude),

    countycode:
      clean(record.countycode),

    areacode:
      clean(record.areacode),

    city:
      clean(record.city),

    cityName:
      clean(record.cityName),

    source:
      clean(record.source)
  };

  const statusKey =
    detectStatus(normalized);

  const specialKey =
    detectSpecialType(normalized);

  return {
    ...normalized,

    statusKey,

    statusLabel:
      statusLabel(statusKey),

    specialKey,

    specialLabel:
      specialLabel(specialKey)
  };
}

/* =========================================================
   讀取 JSON 快照
========================================================= */

function readSnapshotFile(
  filename,
  defaults = {}
) {
  const filePath =
    path.join(
      process.cwd(),
      "docs",
      filename
    );

  if (
    !fs.existsSync(filePath)
  ) {
    console.error(
      `找不到快照：${filePath}`
    );

    return [];
  }

  const raw =
    fs.readFileSync(
      filePath,
      "utf8"
    );

  const parsed =
    JSON.parse(raw);

  const source =
    Array.isArray(parsed)
      ? parsed
      : Array.isArray(parsed?.data)
        ? parsed.data
        : [];

  return source
    .map(
      (record) =>
        enrichRecord({
          ...record,

          city:
            record.city ||
            defaults.city ||
            "",

          cityName:
            record.cityName ||
            defaults.cityName ||
            "",

          source:
            record.source ||
            defaults.source ||
            ""
        })
    )
    .filter(
      (record) =>
        Number.isFinite(
          record.latitude
        ) &&
        Number.isFinite(
          record.longitude
        )
    );
}

/* =========================================================
   新北快照
========================================================= */

async function loadNewTaipeiSnapshot() {
  if (
    newTaipeiSnapshotCache
  ) {
    return newTaipeiSnapshotCache;
  }

  if (
    newTaipeiSnapshotPromise
  ) {
    return newTaipeiSnapshotPromise;
  }

  newTaipeiSnapshotPromise =
    Promise.resolve()
      .then(() => {
        newTaipeiSnapshotCache =
          readSnapshotFile(
            "parking-newtaipei.json",
            {
              city:
                "NewTaipei",

              cityName:
                "新北市",

              source:
                "ntpc-snapshot"
            }
          );

        return newTaipeiSnapshotCache;
      });

  try {
    return await newTaipeiSnapshotPromise;
  } finally {
    newTaipeiSnapshotPromise =
      null;
  }
}

/* =========================================================
   台北快照
========================================================= */

async function loadTaipeiSnapshot() {
  if (
    taipeiSnapshotCache
  ) {
    return taipeiSnapshotCache;
  }

  if (
    taipeiSnapshotPromise
  ) {
    return taipeiSnapshotPromise;
  }

  taipeiSnapshotPromise =
    Promise.resolve()
      .then(() => {
        taipeiSnapshotCache =
          readSnapshotFile(
            "parking-taipei.json",
            {
              city:
                "Taipei",

              cityName:
                "台北市",

              source:
                "taipei-static"
            }
          );

        return taipeiSnapshotCache;
      });

  try {
    return await taipeiSnapshotPromise;
  } finally {
    taipeiSnapshotPromise =
      null;
  }
}

/* =========================================================
   新北政府即時資料
========================================================= */

function normalizeNewTaipeiLive(row) {
  const latitude =
    Number(
      getValue(
        row,
        "latitude",
        "Latitude",
        "LATITUDE",
        "定位坐標[緯度]",
        "定位坐標 [緯度]",
        "緯度"
      )
    );

  const longitude =
    Number(
      getValue(
        row,
        "longitude",
        "Longitude",
        "LONGITUDE",
        "定位坐標[經度]",
        "定位坐標 [經度]",
        "經度"
      )
    );

  if (
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    latitude < 24 ||
    latitude > 26 ||
    longitude < 120 ||
    longitude > 123
  ) {
    return null;
  }

  return enrichRecord({
    id:
      getValue(
        row,
        "id",
        "ID",
        "系統編號"
      ),

    cellid:
      getValue(
        row,
        "cellid",
        "CELLID",
        "CellID",
        "車格編號"
      ),

    name:
      getValue(
        row,
        "name",
        "NAME",
        "類型"
      ),

    day:
      getValue(
        row,
        "day",
        "DAY",
        "開放停車日說明"
      ),

    hour:
      getValue(
        row,
        "hour",
        "HOUR",
        "開放停車時間說明"
      ),

    pay:
      getValue(
        row,
        "pay",
        "PAY",
        "收費方式"
      ),

    paycash:
      getValue(
        row,
        "paycash",
        "PAYCASH",
        "收費計價"
      ),

    memo:
      getValue(
        row,
        "memo",
        "MEMO",
        "備註"
      ),

    roadid:
      getValue(
        row,
        "roadid",
        "ROADID",
        "路段代碼"
      ),

    roadname:
      getValue(
        row,
        "roadname",
        "ROADNAME",
        "路段名稱"
      ),

    cellstatus:
      getValue(
        row,
        "cellstatus",
        "CELLSTATUS",
        "車格狀態"
      ),

    isnowcash:
      getValue(
        row,
        "isnowcash",
        "ISNOWCASH",
        "紀錄現在有無收費"
      ),

    parkingstatus:
      getValue(
        row,
        "parkingstatus",
        "PARKINGSTATUS",
        "ParkingStatus",
        "停車狀態"
      ),

    latitude,

    longitude,

    countycode:
      getValue(
        row,
        "countycode",
        "COUNTYCODE",
        "縣市代碼"
      ),

    areacode:
      getValue(
        row,
        "areacode",
        "AREACODE",
        "鄉鎮代碼"
      ),

    city:
      "NewTaipei",

    cityName:
      "新北市",

    source:
      "ntpc-live"
  });
}

async function fetchNewTaipeiLive() {
  const response =
    await fetch(
      `${NTPC_CSV_URL}?t=${Date.now()}`,
      {
        method:
          "GET",

        headers: {
          Accept:
            "text/csv,*/*",

          "User-Agent":
            "Smart-Parking-App/1.1.2",

          "Cache-Control":
            "no-cache"
        },

        cache:
          "no-store"
      }
    );

  if (
    !response.ok
  ) {
    throw new Error(
      `NTPC HTTP ${response.status}`
    );
  }

  const text =
    await response.text();

  return parseCSV(text)
    .map(
      normalizeNewTaipeiLive
    )
    .filter(Boolean);
}

/* =========================================================
   對應車格 ID
========================================================= */

function parkingKey(record) {
  const cellid =
    clean(record.cellid);

  if (cellid) {
    return `cell:${cellid}`;
  }

  const id =
    clean(record.id);

  if (id) {
    return `id:${id}`;
  }

  return "";
}

/* =========================================================
   最新狀態合併到快照

   重要：
   - 保留快照 latitude / longitude
   - 只更新政府最新狀態及可能變動欄位
========================================================= */

function mergeLiveIntoSnapshot(
  snapshot,
  liveData
) {
  const liveMap =
    new Map();

  for (
    const live
    of liveData
  ) {
    const key =
      parkingKey(live);

    if (key) {
      liveMap.set(
        key,
        live
      );
    }
  }

  return snapshot.map(
    (saved) => {
      const key =
        parkingKey(saved);

      if (!key) {
        return saved;
      }

      const live =
        liveMap.get(key);

      if (!live) {
        return saved;
      }

      return enrichRecord({
        ...saved,

        /*
          位置永遠沿用已存快照
        */
        latitude:
          saved.latitude,

        longitude:
          saved.longitude,

        /*
          即時更新資訊
        */
        cellstatus:
          live.cellstatus,

        parkingstatus:
          live.parkingstatus,

        isnowcash:
          live.isnowcash,

        day:
          live.day ||
          saved.day,

        hour:
          live.hour ||
          saved.hour,

        pay:
          live.pay ||
          saved.pay,

        paycash:
          live.paycash ||
          saved.paycash,

        memo:
          live.memo ||
          saved.memo,

        name:
          live.name ||
          saved.name,

        roadname:
          live.roadname ||
          saved.roadname,

        source:
          "ntpc-live"
      });
    }
  );
}

/* =========================================================
   BBOX
========================================================= */

function parseNumber(value) {
  const number =
    Number(value);

  return Number.isFinite(number)
    ? number
    : null;
}

function parseBBox(
  searchParams
) {
  const west =
    parseNumber(
      searchParams.get(
        "west"
      )
    );

  const east =
    parseNumber(
      searchParams.get(
        "east"
      )
    );

  const south =
    parseNumber(
      searchParams.get(
        "south"
      )
    );

  const north =
    parseNumber(
      searchParams.get(
        "north"
      )
    );

  if (
    west === null ||
    east === null ||
    south === null ||
    north === null
  ) {
    return null;
  }

  if (
    west >= east ||
    south >= north ||
    west < 118 ||
    east > 124 ||
    south < 20 ||
    north > 27
  ) {
    return null;
  }

  return {
    west,
    east,
    south,
    north
  };
}

function isInsideBBox(
  record,
  bbox
) {
  return (
    record.longitude >=
      bbox.west &&
    record.longitude <=
      bbox.east &&
    record.latitude >=
      bbox.south &&
    record.latitude <=
      bbox.north
  );
}

function parseLimit(
  searchParams
) {
  const requested =
    Number(
      searchParams.get(
        "limit"
      )
    );

  if (
    !Number.isFinite(
      requested
    )
  ) {
    return DEFAULT_LIMIT;
  }

  return Math.max(
    100,
    Math.min(
      MAX_LIMIT,
      Math.floor(
        requested
      )
    )
  );
}

/* =========================================================
   API
========================================================= */

module.exports =
async function handler(
  request,
  response
) {
  response.setHeader(
    "Access-Control-Allow-Origin",
    "*"
  );

  response.setHeader(
    "Access-Control-Allow-Methods",
    "GET,OPTIONS"
  );

  response.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type"
  );

  response.setHeader(
    "Cache-Control",
    "no-store, no-cache, must-revalidate"
  );

  if (
    request.method ===
    "OPTIONS"
  ) {
    response.statusCode =
      204;

    response.end();

    return;
  }

  if (
    request.method !==
    "GET"
  ) {
    response.statusCode =
      405;

    response.end(
      "Method Not Allowed"
    );

    return;
  }

  const requestURL =
    new URL(
      request.url,
      "http://localhost"
    );

  const bbox =
    parseBBox(
      requestURL.searchParams
    );

  const limit =
    parseLimit(
      requestURL.searchParams
    );

  const forceRefresh =
    requestURL.searchParams.get(
      "refresh"
    ) === "1";

  /*
    沒有 bbox：
    只回 API 健康狀態
  */
  if (
    !bbox
  ) {
    response.setHeader(
      "Content-Type",
      "application/json; charset=utf-8"
    );

    response.statusCode =
      200;

    response.end(
      JSON.stringify({
        success:
          true,

        mode:
          "summary",

        version:
          "1.1.2",

        loadingMode:
          "snapshot-first",

        message:
          "API 正常。一般載入使用快照；refresh=1 才取得新北最新狀態。",

        data:
          []
      })
    );

    return;
  }

  /*
    先讀本機快照。
    這一步完全不連政府 API。
  */
  const [
    savedNewTaipei,
    taipei
  ] =
    await Promise.all([
      loadNewTaipeiSnapshot(),
      loadTaipeiSnapshot()
    ]);

  let newTaipei =
    savedNewTaipei;

  let ntpcMode =
    "snapshot";

  let refreshed =
    false;

  let refreshError =
    null;

  /*
    只有使用者按重新整理
    才進這裡。
  */
  if (
    forceRefresh
  ) {
    try {
      const live =
        await fetchNewTaipeiLive();

      newTaipei =
        mergeLiveIntoSnapshot(
          savedNewTaipei,
          live
        );

      ntpcMode =
        "live";

      refreshed =
        true;
    } catch (error) {
      console.error(
        "新北即時更新失敗：",
        error
      );

      /*
        即時 API 壞掉也不要讓地圖消失。
        保留原本快照。
      */
      newTaipei =
        savedNewTaipei;

      ntpcMode =
        "snapshot-fallback";

      refreshError =
        error?.message ||
        String(error);
    }
  }

  const inViewNewTaipei =
    newTaipei.filter(
      (record) =>
        isInsideBBox(
          record,
          bbox
        )
    );

  const inViewTaipei =
    taipei.filter(
      (record) =>
        isInsideBBox(
          record,
          bbox
        )
    );

  const allInView = [
    ...inViewNewTaipei,
    ...inViewTaipei
  ];

  const truncated =
    allInView.length >
    limit;

  const data =
    allInView.slice(
      0,
      limit
    );

  response.setHeader(
    "Content-Type",
    "application/json; charset=utf-8"
  );

  response.statusCode =
    200;

  response.end(
    JSON.stringify({
      success:
        true,

      mode:
        "bbox",

      version:
        "1.1.2",

      loadingMode:
        forceRefresh
          ? "manual-refresh"
          : "snapshot",

      generatedAt:
        new Date()
          .toISOString(),

      bbox,

      counts: {
        newTaipei:
          inViewNewTaipei.length,

        taipei:
          inViewTaipei.length,

        total:
          allInView.length,

        returned:
          data.length
      },

      sourceTotals: {
        newTaipei:
          savedNewTaipei.length,

        taipei:
          taipei.length
      },

      truncated,

      limit,

      refreshed,

      ntpcMode,

      refreshError,

      data
    })
  );
};
const fs = require("fs");
const path = require("path");

/* =========================================================
   Smart Parking API v1.1.0
   - 新北：政府即時資料，記憶體快取 2 分鐘
   - 台北：讀取 docs/parking-taipei.json
   - 只回傳目前地圖 bbox 內資料
========================================================= */

const NTPC_DATASET_ID =
  "54A507C4-C038-41B5-BF60-BBECB9D052C6";

const NTPC_CSV_URL =
  `https://data.ntpc.gov.tw/api/datasets/${NTPC_DATASET_ID}/csv/file`;

const NTPC_CACHE_MS = 120 * 1000;
const DEFAULT_LIMIT = 5000;
const MAX_LIMIT = 8000;

let taipeiCache = null;
let taipeiLoadPromise = null;

let ntpcCache = {
  data: [],
  loadedAt: 0,
  promise: null
};

function clean(value) {
  if (value === undefined || value === null) {
    return "";
  }

  return String(value).trim();
}

function getValue(row, ...keys) {
  if (!row) return "";

  const lowerMap = {};

  for (const [key, value] of Object.entries(row)) {
    lowerMap[String(key).toLowerCase()] = value;
  }

  for (const key of keys) {
    if (
      Object.prototype.hasOwnProperty.call(row, key) &&
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
      String(lowerMap[lowerKey]).trim() !== ""
    ) {
      return lowerMap[lowerKey];
    }
  }

  return "";
}

/* =========================================================
   CSV
========================================================= */

function parseCSV(text) {
  text =
    String(text || "").replace(/^\uFEFF/, "");

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
   狀態 / 特殊車格
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
  const statusKey =
    detectStatus(record);

  const specialKey =
    detectSpecialType(record);

  return {
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
      clean(record.source),

    statusKey,

    statusLabel:
      statusLabel(statusKey),

    specialKey,

    specialLabel:
      specialLabel(specialKey)
  };
}

/* =========================================================
   新北市
========================================================= */

function normalizeNewTaipei(row) {
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
      "ntpc"
  });
}

async function fetchNewTaipei(
  forceRefresh = false
) {
  const now =
    Date.now();

  if (
    !forceRefresh &&
    ntpcCache.data.length &&
    now - ntpcCache.loadedAt <
      NTPC_CACHE_MS
  ) {
    return ntpcCache.data;
  }

  if (
    ntpcCache.promise
  ) {
    return ntpcCache.promise;
  }

  ntpcCache.promise =
    (async () => {
      const url =
        `${NTPC_CSV_URL}?t=${Date.now()}`;

      const response =
        await fetch(
          url,
          {
            method:
              "GET",

            headers: {
              Accept:
                "text/csv,*/*",

              "User-Agent":
                "Smart-Parking-App/1.1",

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

      const data =
        parseCSV(text)
          .map(
            normalizeNewTaipei
          )
          .filter(Boolean);

      ntpcCache.data =
        data;

      ntpcCache.loadedAt =
        Date.now();

      return data;
    })();

  try {
    return await ntpcCache.promise;
  } finally {
    ntpcCache.promise =
      null;
  }
}

/* =========================================================
   台北市快照
========================================================= */

async function loadTaipei() {
  if (
    taipeiCache
  ) {
    return taipeiCache;
  }

  if (
    taipeiLoadPromise
  ) {
    return taipeiLoadPromise;
  }

  taipeiLoadPromise =
    Promise.resolve()
      .then(() => {
        const filePath =
          path.join(
            process.cwd(),
            "docs",
            "parking-taipei.json"
          );

        if (
          !fs.existsSync(
            filePath
          )
        ) {
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
            : Array.isArray(
                parsed?.data
              )
              ? parsed.data
              : [];

        taipeiCache =
          source
            .map(
              (record) =>
                enrichRecord({
                  ...record,

                  city:
                    record.city ||
                    "Taipei",

                  cityName:
                    record.cityName ||
                    "台北市",

                  source:
                    record.source ||
                    "taipei-static"
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

        return taipeiCache;
      });

  try {
    return await taipeiLoadPromise;
  } finally {
    taipeiLoadPromise =
      null;
  }
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
    沒有 bbox 時只做快速健康檢查，
    不載入 11 萬筆資料。
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
          "1.1.0",

        message:
          "API 正常。請提供 west/east/south/north 取得目前地圖範圍內的停車格。",

        data:
          []
      })
    );

    return;
  }

  let newTaipei =
    [];

  let ntpcMode =
    "live";

  try {
    newTaipei =
      await fetchNewTaipei(
        forceRefresh
      );
  } catch (error) {
    console.error(
      "新北即時資料取得失敗：",
      error
    );

    ntpcMode =
      "unavailable";

    if (
      ntpcCache.data.length
    ) {
      newTaipei =
        ntpcCache.data;

      ntpcMode =
        "memory-cache";
    }
  }

  const taipei =
    await loadTaipei();

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
        "1.1.0",

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
          newTaipei.length,

        taipei:
          taipei.length
      },

      truncated,

      limit,

      ntpcMode,

      data
    })
  );
};
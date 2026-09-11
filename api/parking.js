const DATASET_ID =
  "54A507C4-C038-41B5-BF60-BBECB9D052C6";

const GOVERNMENT_URL =
  `https://data.ntpc.gov.tw/api/datasets/${DATASET_ID}/csv/file`;


export default async function handler(req, res) {

  // ================================
  // CORS
  // ================================

  res.setHeader(
    "Access-Control-Allow-Origin",
    "*"
  );

  res.setHeader(
    "Access-Control-Allow-Methods",
    "GET, OPTIONS"
  );

  res.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type"
  );


  if (req.method === "OPTIONS") {

    return res
      .status(204)
      .end();

  }


  if (req.method !== "GET") {

    return res
      .status(405)
      .json({
        success: false,
        error: "Method Not Allowed"
      });

  }


  try {

    // 每一次重新整理
    // 都重新向政府 API 取資料

    const governmentResponse =
      await fetch(
        `${GOVERNMENT_URL}?t=${Date.now()}`,
        {
          method: "GET",

          headers: {
            Accept: "text/csv,*/*;q=0.8",

            "User-Agent":
              "SmartParkingApp/1.0.4",

            "Cache-Control":
              "no-cache"
          },

          cache: "no-store"
        }
      );


    if (!governmentResponse.ok) {

      throw new Error(
        `Government API HTTP ${governmentResponse.status}`
      );

    }


    const csv =
      await governmentResponse.text();


    res.setHeader(
      "Content-Type",
      "text/csv; charset=utf-8"
    );

    res.setHeader(
      "Cache-Control",
      "no-store, no-cache, must-revalidate"
    );

    return res
      .status(200)
      .send(csv);


  } catch (error) {

    console.error(error);


    return res
      .status(502)
      .json({
        success: false,
        error: "無法取得政府停車資料",
        detail: String(error)
      });

  }

}

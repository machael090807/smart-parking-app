const DATASET_ID =
  "54A507C4-C038-41B5-BF60-BBECB9D052C6";

const GOVERNMENT_CSV_URL =
  `https://data.ntpc.gov.tw/api/datasets/${DATASET_ID}/csv/file`;


export default {

  async fetch(request) {

    const url =
      new URL(request.url);


    /* =========================================
       CORS Preflight
    ========================================= */

    if (
      request.method === "OPTIONS"
    ) {

      return new Response(
        null,
        {
          status: 204,

          headers: {

            "Access-Control-Allow-Origin":
              "*",

            "Access-Control-Allow-Methods":
              "GET, OPTIONS",

            "Access-Control-Allow-Headers":
              "Content-Type",

            "Access-Control-Max-Age":
              "86400"

          }
        }
      );

    }


    /* =========================================
       Health
    ========================================= */

    if (
      url.pathname === "/"
    ) {

      return new Response(

        JSON.stringify({

          success:
            true,

          service:
            "Smart Parking Live API",

          version:
            "1.0.4"

        }),

        {

          headers: {

            "Content-Type":
              "application/json; charset=utf-8",

            "Access-Control-Allow-Origin":
              "*"

          }

        }

      );

    }


    /* =========================================
       Parking API
    ========================================= */

    if (
      url.pathname !== "/parking"
    ) {

      return new Response(

        "Not Found",

        {
          status: 404
        }

      );

    }


    try {


      /*
        每次呼叫 /parking
        都重新向新北市政府取得資料

        不使用 Cloudflare cache
      */

      const governmentURL =

        GOVERNMENT_CSV_URL +

        "?t=" +

        Date.now();



      const response =

        await fetch(

          governmentURL,

          {

            method:
              "GET",

            headers: {

              "Accept":
                "text/csv,*/*;q=0.8",

              "User-Agent":
                "SmartParkingApp/1.0.4",

              "Cache-Control":
                "no-cache"

            },

            cf: {

              cacheTtl:
                0,

              cacheEverything:
                false

            }

          }

        );



      if (
        !response.ok
      ) {

        throw new Error(

          `Government API HTTP ${response.status}`

        );

      }



      const body =
        await response.arrayBuffer();



      return new Response(

        body,

        {

          status:
            200,

          headers: {

            "Content-Type":
              "text/csv; charset=utf-8",

            "Access-Control-Allow-Origin":
              "*",

            "Cache-Control":
              "no-store, no-cache, must-revalidate",

            "Pragma":
              "no-cache",

            "Expires":
              "0",

            "X-Smart-Parking-Live":
              "true"

          }

        }

      );


    }

    catch (
      error
    ) {


      return new Response(

        JSON.stringify({

          success:
            false,

          error:
            "無法取得政府停車資料",

          detail:
            String(
              error
            )

        }),

        {

          status:
            502,

          headers: {

            "Content-Type":
              "application/json; charset=utf-8",

            "Access-Control-Allow-Origin":
              "*",

            "Cache-Control":
              "no-store"

          }

        }

      );

    }

  }

};

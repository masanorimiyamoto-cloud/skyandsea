const { createApp, ref, computed, onMounted } = Vue

createApp({
  setup() {
    // ---- 1) フォームデータ ----
    const form = ref({
      personid: "",
      workcd: "",
      workname: "",
      bookname: "",
      workprocess: "",
      unitprice: 0,
      workoutput: "0",
      workday: "",
    })

    // ---- 2) 各種リスト ----
    const personidList = ref([])           // [{id:1, name:"Aさん"}, {id:2, name:"Bさん"}...]
    const workprocessList = ref([])        // ["分給", "梱包", ...]
    const unitpriceDict = ref({})          // {"分給": 500, "梱包": 1000, ...}
    const workcordDict = ref({})          // {"123": [{workname:"XXX", bookname:"YYY"}, ...], ...}

    // 品名候補表示用
    const workNameCandidates = ref([])     // [{workname, bookname}, ...]
    // どの品名を選んだか
    const selectedWorkName = ref(null)

    // ---- 3) メッセージ表示 (成功/失敗) ----
    const message = ref({
      text: "",
      type: "", // "success" or "error"
    })

    // ---- 4) 初期処理: サーバから init-data をまとめて取得 ----
    onMounted(async () => {
      try {
        const res = await fetch("/api/init-data")
        if (!res.ok) {
          throw new Error("初期データ取得に失敗しました")
        }
        const data = await res.json()
        personidList.value = data.personids || []
        workprocessList.value = data.workprocess_list || []
        unitpriceDict.value = data.unitprice_dict || {}
        workcordDict.value = data.workcord_dict || {}

        // 前回入力した内容を localStorage などから復元したければここで
        loadLocalStorage()
      } catch (err) {
        showMessage(err.message, "error")
      }
    })

    // ---- 5) 「品名候補を取得」ボタン ----
    const fetchWorkNameCandidates = () => {
      const cd = form.value.workcd.trim()
      if (!cd) {
        showMessage("品名コードを入力してください", "error")
        return
      }
      // workcordDict.value が全部持っているので、クライアント側で検索してもOK
      // もしサーバに毎回問い合わせたいなら `/api/worknames/<cd>` に fetch。
      // 今回は init-data でもらっているため、クライアント検索します:
      workNameCandidates.value = workcordDict.value[cd] || []
      if (workNameCandidates.value.length === 0) {
        showMessage("該当する品名がありません", "error")
      } else {
        showMessage(`候補が ${workNameCandidates.value.length} 件見つかりました`, "success")
      }
    }

    // ---- 6) selectedWorkName が変わったときに form の workname/bookname を同期 ----
    const updateSelectedWorkName = () => {
      if (!selectedWorkName.value) {
        form.value.workname = ""
        form.value.bookname = ""
        return
      }
      form.value.workname = selectedWorkName.value.workname
      form.value.bookname = selectedWorkName.value.bookname
    }

    // ---- 7) 行程が変わったら単価を更新 ----
    const updateUnitPrice = () => {
      const wp = form.value.workprocess
      if (!wp) {
        form.value.unitprice = 0
      } else {
        form.value.unitprice = unitpriceDict.value[wp] || 0
      }
    }

    // ---- 8) フォーム送信 ----
    const handleSubmit = async () => {
      // 適宜バリデーション
      if (!form.value.personid) {
        showMessage("PersonID を選択してください", "error")
        return
      }
      if (!form.value.workday) {
        showMessage("作業日を選んでください", "error")
        return
      }
      try {
        // 送信用オブジェクト
        const payload = {
          personid: form.value.personid,
          workcd: form.value.workcd,
          workname: form.value.workname,
          bookname: form.value.bookname,
          workprocess: form.value.workprocess,
          unitprice: parseFloat(form.value.unitprice || 0),
          workoutput: parseInt(form.value.workoutput || "0", 10),
          workday: form.value.workday,
        }
        const res = await fetch("/api/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
        const data = await res.json()
        if (!res.ok) {
          throw new Error(data.error || "送信に失敗しました")
        }
        showMessage("✅ 送信成功: " + data.message, "success")
        saveLocalStorage() // ローカルストレージへの保存など
      } catch (err) {
        showMessage(err.message, "error")
      }
    }

    // ---- 9) 一覧ページへ移動（Flaskの /records に移動したいなど）----
    const goToRecords = () => {
      window.location.href = "/records"
    }

    // ---- ローカルストレージ保存/復元 (任意) ----
    const saveLocalStorage = () => {
      localStorage.setItem("personid", form.value.personid)
      localStorage.setItem("workday", form.value.workday)
    }
    const loadLocalStorage = () => {
      const savedPid = localStorage.getItem("personid") || ""
      const savedDay = localStorage.getItem("workday") || ""
      form.value.personid = savedPid
      form.value.workday = savedDay
    }

    // ---- メッセージ表示関数 ----
    const showMessage = (text, type) => {
      message.value.text = text
      message.value.type = type
      // 数秒後にメッセージ消したい場合など
      setTimeout(() => {
        message.value.text = ""
        message.value.type = ""
      }, 3000)
    }

    // ---- ウォッチ: selectedWorkName が変わったら反映 ----
    // Vue 3 の場合、computed でも watch でも可
    // ここでは watch で実装
    watchEffect(() => {
      updateSelectedWorkName()
    })

    // ---- 返却 (テンプレートで使う変数・メソッド) ----
    return {
      form,
      personidList,
      workprocessList,
      unitpriceDict,
      workcordDict,
      workNameCandidates,
      selectedWorkName,

      message,
      fetchWorkNameCandidates,
      updateUnitPrice,
      handleSubmit,
      goToRecords,
    }
  },
}).mount("#app")

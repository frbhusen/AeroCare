// Clinical note snippets & templates picker
import { h, t } from "../core/index.js";
import { icon } from "./icons.js";
import { popover } from "./modal.js";

const DEFAULT_SNIPPETS = {
  // Clinical Examination & Findings
  examination_findings: [
    {
      en: "Physical examination within normal limits. No signs of acute distress or infection.",
      ar: "الفحص السريري سليم وضمن الحدود الطبيعية. لا توجد علامات ضائقة حادة أو التهاب."
    },
    {
      en: "Localized erythematous maculopapular rash, non-tender, no scaling or weeping.",
      ar: "طفح بقعي حطاطي حمامي موضعي، غير مؤلم، دون تقشر أو نضح."
    },
    {
      en: "Clear cornea and anterior chamber, pupillary reflexes brisk and symmetrical bilaterally.",
      ar: "القرنية والغرفة الأمامية شفافتان، المنعكسات الحليمية نشطة ومتناظرة في كلا العينين."
    },
    {
      en: "Oral mucosa pink and moist, mild marginal gingival inflammation around lower molars.",
      ar: "الغشاء المخاطي الفموي وردي ورطب، التهاب لثة حفافي طفيف حول الأرحاء السفلية."
    }
  ],

  // Symptoms & Chief Complaints
  symptoms: [
    {
      en: "Mild pruritus and localized discomfort for 3 days, exacerbated by heat.",
      ar: "حكة خفيفة وانزعاج موضعي منذ 3 أيام، يتفاقم مع التعرض للحرارة."
    },
    {
      en: "Gradual painless blurring of distant vision in both eyes over past 2 months.",
      ar: "تراجع تدريجي غير مؤلم في الرؤية البعيدة بكلتا العينين خلال الشهرين الماضيين."
    },
    {
      en: "Mild localized pain provoked by hot and cold stimuli, resolving shortly after.",
      ar: "ألم موضعي خفيف يثار بالحرارة والبرودة ويزول بعد فترة قصيرة."
    }
  ],

  // Diagnosis
  diagnosis: [
    {
      en: "Contact dermatitis (mild, irritant type).",
      ar: "التهاب جلد تماسي (خفيف، نمط تخريشي)."
    },
    {
      en: "Refractive error (Simple Myopia / Astigmatism).",
      ar: "عيب انكساري (حسر بصر بسيط / حرج بصر)."
    },
    {
      en: "Class I Dental Caries with reversible pulpitis.",
      ar: "نخر سني صنف أول مع التهاب لب عكوس."
    },
    {
      en: "Post-inflammatory hyperpigmentation.",
      ar: "فرط تصبغ تالٍ للالتهاب."
    }
  ],

  // Treatment Plans
  treatment: [
    {
      en: "Topical emollient applied twice daily. Avoid scented soaps and harsh detergents.",
      ar: "تطبيق مرطب موضعي مرتين يومياً. تجنب الصابون المعطر والمنظفات الكيميائية."
    },
    {
      en: "Preservative-free artificial tears 1 drop 4 times daily as needed for dry eye relief.",
      ar: "قطرة دموع اصطناعية خالية من المواد الحافظة قطرة واحدة 4 مرات يومياً حسب الحاجة."
    },
    {
      en: "Tooth restoration completed with light-cured composite resin. Oral hygiene reinforced.",
      ar: "تمت حشوة السن براتنج الكمبوزيت الضوئي. تم التأكيد على تعليمات العناية الفموية."
    },
    {
      en: "Follow-up in 2 weeks or sooner if symptoms worsen.",
      ar: "مراجعة العيادة بعد أسبوعين أو قبل ذلك في حال تفاقم الأعراض."
    }
  ],

  // Notes & Laser Parameters
  notes: [
    {
      en: "Patient tolerated the procedure well. No adverse reactions observed during or after session.",
      ar: "تحمل المريض الإجراء بشكل جيد. لم تُلاحظ أي تأثيرات جانبية أثناء أو بعد الجلسة."
    },
    {
      en: "Laser session completed with standard cooling and fluence parameters. Mild expected transient erythema.",
      ar: "تمت جلسة الليزر بمعايير التبريد والحرارة المعتمدة. احمرار خفيف متوقع ومؤقت."
    },
    {
      en: "Strict sun protection advised with broad-spectrum SPF 50+ sunscreen applied every 2 hours outdoors.",
      ar: "تم التأكيد على الوقاية الصارمة من الشمس واستخدام واقٍ شمسي SPF 50+ وتجديده كل ساعتين خارجاً."
    },
    {
      en: "Next session recommended in 4-6 weeks.",
      ar: "يُنصح بالجلسة القادمة بعد 4 إلى 6 أسابيع."
    }
  ]
};

// Aliases for matching fields
DEFAULT_SNIPPETS.chief_complaint = DEFAULT_SNIPPETS.symptoms;
DEFAULT_SNIPPETS.history = DEFAULT_SNIPPETS.symptoms;
DEFAULT_SNIPPETS.condition = DEFAULT_SNIPPETS.diagnosis;

/**
 * Returns snippet button element for a textarea
 */
export function snippetButton(textarea, fieldName, customSnippets) {
  const snippets = customSnippets || DEFAULT_SNIPPETS[fieldName] || DEFAULT_SNIPPETS.notes;
  if (!snippets || !snippets.length) return null;

  const btn = h("button", {
    class: "snippet-trigger-btn",
    type: "button",
    title: t("core.snippets.btn", { default: "Quick Note Templates" }),
    "aria-label": t("core.snippets.btn", { default: "Quick Note Templates" })
  },
  icon("fileText"),
  h("span", t("core.snippets.title", { default: "Templates" }))
  );

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();

    const isAr = document.documentElement.lang === "ar" || document.documentElement.dir === "rtl";
    let pop;

    const list = h("div", { class: "snippet-popover-list" });

    snippets.forEach((item) => {
      const text = isAr ? (item.ar || item.en) : (item.en || item.ar);
      const row = h("button", {
        class: "snippet-item",
        type: "button",
        onClick: () => {
          pop.close();
          const current = textarea.value.trim();
          if (!current) {
            textarea.value = text;
          } else {
            textarea.value = current + "\n" + text;
          }
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
          textarea.focus();
        }
      },
      h("span", { class: "snippet-item-text" }, text)
      );
      list.append(row);
    });

    const body = h("div", { class: "snippet-popover-body" },
      h("div", { class: "snippet-popover-header" },
        h("strong", t("core.snippets.header", { default: "Select Clinical Note" })),
        h("span", { class: "text-xs text-muted" }, t("core.snippets.hint", { default: "Click to append" }))
      ),
      list
    );

    pop = popover(btn, body, { className: "snippet-popover" });
  });

  return btn;
}

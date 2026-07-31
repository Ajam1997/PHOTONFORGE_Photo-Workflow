package com.photonforge.core.xmp

import com.photonforge.core.FusionResult
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import javax.xml.parsers.DocumentBuilderFactory
import javax.xml.transform.OutputKeys
import javax.xml.transform.TransformerFactory
import javax.xml.transform.dom.DOMSource
import javax.xml.transform.stream.StreamResult
import org.w3c.dom.Document
import org.w3c.dom.Element

/**
 * XMP sidecar writer: parse-modify-write, never overwrite (the contract from
 * android-port-brief.md §6, matching the desktop fix in PR #142 and extending it
 * with the standard properties darktable ingests from sidecars):
 *
 *   - photon:* analysis block (namespace https://photonforge.local/xmp/1.0/)
 *   - xmp:Rating (-1..5), xmp:Label (Blue/Green/Yellow)
 *   - lr:hierarchicalSubject + dc:subject (photon|subject|x, photon|type|y,
 *     photon|needs_review) — single tag per axis
 *
 * Anything outside those properties — darktable:history_*, masks, unknown
 * namespaces — is preserved verbatim at the DOM level.
 */
object XmpSidecar {

    const val PHOTON_NS = "https://photonforge.local/xmp/1.0/"
    const val RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    const val XMP_NS = "http://ns.adobe.com/xap/1.0/"
    const val DC_NS = "http://purl.org/dc/elements/1.1/"
    const val LR_NS = "http://ns.adobe.com/lightroom/1.0/"
    const val X_NS = "adobe:ns:meta/"

    const val SUBJECT_TAG_PREFIX = "photon|subject|"
    const val TYPE_TAG_PREFIX = "photon|type|"
    const val NEEDS_REVIEW_TAG = "photon|needs_review"

    private const val XPACKET_HEADER = "<?xpacket begin='﻿' id='W5M0MpCehiHzreSzNTczkc9d'?>"
    private const val XPACKET_FOOTER = "<?xpacket end='w'?>"

    data class SidecarData(
        val fusion: FusionResult,
        val semanticName: String = "",
        val originalFilename: String,
        val sessionId: String,
        val isDuplicate: Boolean,
        val rating: Int,                     // -1 reject .. 5 (hybrid/absolute star or user override)
        val sharpnessOverall: Double,        // module overall scores (desktop record.*_score)
        val compositionOverall: Double,
        val exposureOverall: Double,
        val blurType: String,
        val exposureStyle: String,
    )

    fun labelString(colorLabel: Int): String? = when (colorLabel) {
        0 -> "Red"
        1 -> "Yellow"
        2 -> "Green"
        3 -> "Blue"
        4 -> "Purple"
        else -> null
    }

    /** existing: current sidecar bytes or null; returns the new sidecar text. */
    fun render(existing: ByteArray?, data: SidecarData): String {
        val doc: Document = if (existing != null && existing.isNotEmpty()) {
            parse(existing) ?: freshDocument()
        } else {
            freshDocument()
        }
        val desc = findOrCreateDescription(doc)

        // --- photon:* block: drop then re-add -------------------------------
        val toRemove = ArrayList<Element>()
        var child = desc.firstChild
        while (child != null) {
            if (child is Element && PHOTON_NS == child.namespaceURI) toRemove.add(child)
            child = child.nextSibling
        }
        toRemove.forEach { desc.removeChild(it) }
        val attrs = desc.attributes
        val attrRemove = ArrayList<String>()
        for (i in 0 until attrs.length) {
            val a = attrs.item(i)
            if (PHOTON_NS == a.namespaceURI) attrRemove.add(a.nodeName)
        }
        attrRemove.forEach { desc.removeAttribute(it) }

        val f = data.fusion
        val ss = f.subScores
        fun photonEl(name: String, value: String) {
            val el = doc.createElementNS(PHOTON_NS, "photon:$name")
            el.textContent = value
            desc.appendChild(el)
        }
        photonEl("SharpnessScore", num(data.sharpnessOverall))
        photonEl("CompositionScore", num(data.compositionOverall))
        photonEl("ExposureScore", num(data.exposureOverall))
        photonEl("SemanticName", data.semanticName)
        photonEl("OriginalFilename", data.originalFilename)
        photonEl("SessionID", data.sessionId)
        photonEl("IsDuplicate", data.isDuplicate.toString())
        photonEl("Genre", f.subject)
        photonEl("GenreConfidence", num(f.subjectConfidence))
        photonEl("MasterScore", num(f.masterScore))
        run {
            val genres = doc.createElementNS(PHOTON_NS, "photon:Genres")
            val bag = doc.createElementNS(RDF_NS, "rdf:Bag")
            for (g in listOf(f.subject, f.photoType)) {
                val li = doc.createElementNS(RDF_NS, "rdf:li")
                li.textContent = g
                bag.appendChild(li)
            }
            genres.appendChild(bag)
            desc.appendChild(genres)
        }
        photonEl("NeedsReview", f.needsReview.toString())
        photonEl("EyeSharpness", num(ss["eye_sharpness"]))
        photonEl("SubjectSharpness", num(ss["subject_sharpness"]))
        photonEl("SubjectIsolation", num(ss["subject_isolation"]))
        photonEl("BlurType", data.blurType)
        photonEl("CompositionRoT", num(ss["composition_rot"]))
        photonEl("Symmetry", num(ss["symmetry"]))
        photonEl("LeadingLines", num(ss["leading_lines"]))
        photonEl("NegativeSpace", num(ss["negative_space"]))
        photonEl("ZoneEntropy", num(ss["zone_entropy"]))
        photonEl("DynamicRange", num(ss["dynamic_range"]))
        photonEl("ExposureStyle", data.exposureStyle)
        photonEl("FaceExposure", num(ss["face_exposure"]))
        photonEl("AestheticScore", num(ss["aesthetic_clip"]))
        photonEl("PhotoType", f.photoType)
        photonEl("PhotoTypeConfidence", num(f.typeConfidence))
        photonEl("HardReject", f.hardReject.toString())
        if (f.hardRejectReason.isNotEmpty()) photonEl("HardRejectReason", f.hardRejectReason)

        // --- standard properties darktable reads ---------------------------
        desc.setAttributeNS(XMP_NS, "xmp:Rating", data.rating.toString())
        val label = labelString(f.colorLabel)
        if (label != null && f.colorLabel != 4) {   // purple never auto-written
            desc.setAttributeNS(XMP_NS, "xmp:Label", label)
        } else {
            // Do not clear a label we didn't write (could be the user's purple).
            val existingLabel = desc.getAttributeNS(XMP_NS, "Label")
            if (existingLabel in listOf("Yellow", "Green", "Blue") && label == null) {
                desc.removeAttributeNS(XMP_NS, "Label")
            }
        }

        // --- tags: photon|* entries in lr:hierarchicalSubject + dc:subject --
        val tags = listOf(
            SUBJECT_TAG_PREFIX + f.subject,
            TYPE_TAG_PREFIX + f.photoType,
        ) + if (f.needsReview) listOf(NEEDS_REVIEW_TAG) else emptyList()
        replacePhotonTags(doc, desc, LR_NS, "lr:hierarchicalSubject", tags)
        replacePhotonTags(doc, desc, DC_NS, "dc:subject", tags)

        return serialize(doc)
    }

    private fun num(v: Any?): String = when (v) {
        null -> "0.0"
        is Double -> if (v == v.toLong().toDouble()) "${v.toLong()}.0" else v.toString()
        else -> v.toString()
    }

    /** Replace photon|* entries in the named rdf:Bag, preserving foreign tags. */
    private fun replacePhotonTags(
        doc: Document,
        desc: Element,
        ns: String,
        qname: String,
        photonTags: List<String>,
    ) {
        val local = qname.substringAfter(":")
        var container: Element? = null
        var child = desc.firstChild
        while (child != null) {
            if (child is Element && ns == child.namespaceURI && local == child.localName) {
                container = child
                break
            }
            child = child.nextSibling
        }
        if (container == null) {
            container = doc.createElementNS(ns, qname)
            desc.appendChild(container)
        }
        var bag: Element? = null
        var c = container.firstChild
        while (c != null) {
            if (c is Element && RDF_NS == c.namespaceURI && c.localName == "Bag") { bag = c; break }
            c = c.nextSibling
        }
        if (bag == null) {
            bag = doc.createElementNS(RDF_NS, "rdf:Bag")
            container.appendChild(bag)
        }
        // Remove existing photon| entries only.
        val liRemove = ArrayList<Element>()
        var li = bag.firstChild
        while (li != null) {
            if (li is Element && RDF_NS == li.namespaceURI && li.localName == "li" &&
                (li.textContent ?: "").startsWith("photon|")
            ) {
                liRemove.add(li)
            }
            li = li.nextSibling
        }
        liRemove.forEach { bag.removeChild(it) }
        for (t in photonTags) {
            val el = doc.createElementNS(RDF_NS, "rdf:li")
            el.textContent = t
            bag.appendChild(el)
        }
    }

    private fun parse(bytes: ByteArray): Document? = try {
        val dbf = DocumentBuilderFactory.newInstance()
        dbf.isNamespaceAware = true
        dbf.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
        val doc = dbf.newDocumentBuilder().parse(ByteArrayInputStream(bytes))
        // Drop document-level xpacket PIs — we re-add the wrapper on serialize,
        // and keeping them would duplicate the header on every rewrite.
        val piRemove = ArrayList<org.w3c.dom.Node>()
        var n = doc.firstChild
        while (n != null) {
            if (n.nodeType == org.w3c.dom.Node.PROCESSING_INSTRUCTION_NODE) piRemove.add(n)
            n = n.nextSibling
        }
        piRemove.forEach { doc.removeChild(it) }
        doc
    } catch (e: Exception) {
        null
    }

    private fun freshDocument(): Document {
        val dbf = DocumentBuilderFactory.newInstance()
        dbf.isNamespaceAware = true
        val doc = dbf.newDocumentBuilder().newDocument()
        val meta = doc.createElementNS(X_NS, "x:xmpmeta")
        meta.setAttributeNS(X_NS, "x:xmptk", "PHOTONForge-Android")
        doc.appendChild(meta)
        val rdf = doc.createElementNS(RDF_NS, "rdf:RDF")
        meta.appendChild(rdf)
        val desc = doc.createElementNS(RDF_NS, "rdf:Description")
        desc.setAttributeNS(RDF_NS, "rdf:about", "")
        rdf.appendChild(desc)
        return doc
    }

    private fun findOrCreateDescription(doc: Document): Element {
        val list = doc.getElementsByTagNameNS(RDF_NS, "Description")
        if (list.length > 0) return list.item(0) as Element
        var rdf = doc.getElementsByTagNameNS(RDF_NS, "RDF").item(0) as Element?
        if (rdf == null) {
            rdf = doc.createElementNS(RDF_NS, "rdf:RDF")
            doc.documentElement.appendChild(rdf)
        }
        val desc = doc.createElementNS(RDF_NS, "rdf:Description")
        desc.setAttributeNS(RDF_NS, "rdf:about", "")
        rdf.appendChild(desc)
        return desc
    }

    private fun serialize(doc: Document): String {
        val tf = TransformerFactory.newInstance().newTransformer()
        tf.setOutputProperty(OutputKeys.OMIT_XML_DECLARATION, "yes")
        tf.setOutputProperty(OutputKeys.INDENT, "no")
        tf.setOutputProperty(OutputKeys.ENCODING, "UTF-8")
        val out = ByteArrayOutputStream()
        tf.transform(DOMSource(doc), StreamResult(out))
        return "$XPACKET_HEADER\n${out.toString(Charsets.UTF_8.name())}\n$XPACKET_FOOTER\n"
    }

    /** Sidecar filename convention: IMG.ARW -> IMG.ARW.xmp (append, never replace). */
    fun sidecarName(photoName: String): String = "$photoName.xmp"
}
